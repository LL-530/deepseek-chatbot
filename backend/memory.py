"""
memory.py —— 对话记忆管理（★ 本项目核心难点）
------------------------------------------------------------
解决的问题：聊得越久，历史越长，一次性塞给模型就会「token 爆炸」。

这里用两条策略配合：

    策略 A · 滑动窗口（短期记忆）
        原样保留最近 SLIDING_WINDOW_ROUNDS 轮对话，更早的原始消息不再直接送给模型。
        —— 满足「AI 记得你最近 10 轮说过的话」

    策略 B · 摘要压缩（长期记忆）
        当窗口外的未压缩消息攒够 COMPRESS_TRIGGER 条时，
        调模型把它们压成一段 300 字以内的摘要，滚动合并进 conversations.summary，
        并把 summary_upto_id 推进到已压缩的最后一条消息。
        —— 满足「聊得再久也不会 token 爆炸」，同时不丢失关键信息

最终送给模型的内容 = [历史摘要] + [最近 N 轮原始消息]
"""
from __future__ import annotations

from typing import Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

import llm
from config import COMPRESS_TRIGGER, MAX_SUMMARY_INPUT_CHARS, SLIDING_WINDOW_ROUNDS
from db import execute, query_all, query_one

SUMMARY_BLOCK_HEADER = (
    "【本次对话的历史摘要】\n"
    "以下是你和用户更早之前聊过的内容（已压缩）。请把它当作已知事实，"
    "如果用户提到「之前」「上次」等，请结合这段摘要回答。\n"
    "----\n"
)


class ConversationNotFound(Exception):
    """会话不存在或不属于当前用户。"""


class ConversationMemory:
    """一个会话的记忆管理器。"""

    def __init__(self, user_id: int, conversation_id: int):
        self.user_id = user_id
        self.conversation_id = conversation_id

    # ========================================================
    # 基础读取
    # ========================================================
    def get_conversation(self) -> dict:
        row = query_one(
            "SELECT * FROM conversations WHERE id = %s AND user_id = %s",
            (self.conversation_id, self.user_id),
        )
        if not row:
            raise ConversationNotFound(f"会话 {self.conversation_id} 不存在")
        return row

    def _load_uncompressed(self) -> list[dict]:
        """取出「还没被压缩进摘要」的所有消息（按时间正序）。"""
        conv = self.get_conversation()
        return query_all(
            """
            SELECT id, role, content, created_at
            FROM chat_history
            WHERE conversation_id = %s AND id > %s
            ORDER BY id ASC
            """,
            (self.conversation_id, conv["summary_upto_id"]),
        )

    # ========================================================
    # 写入
    # ========================================================
    def add_message(self, role: str, content: str) -> int:
        """存一条消息，返回消息 id。"""
        message_id, _ = execute(
            """
            INSERT INTO chat_history (user_id, conversation_id, role, content)
            VALUES (%s, %s, %s, %s)
            """,
            (self.user_id, self.conversation_id, role, content),
        )
        execute(
            "UPDATE conversations SET updated_at = NOW() WHERE id = %s",
            (self.conversation_id,),
        )
        return message_id

    def touch_title(self, first_user_message: str) -> None:
        """用第一句话给会话起个标题（只在还是「新对话」时生效）。"""
        title = first_user_message.strip().replace("\n", " ")[:24] or "新对话"
        execute(
            "UPDATE conversations SET title = %s WHERE id = %s AND title = '新对话'",
            (title, self.conversation_id),
        )

    # ========================================================
    # 策略 B：摘要压缩
    # ========================================================
    async def compress_if_needed(self) -> Optional[str]:
        """
        判断是否需要压缩。需要就压缩，返回新摘要；否则返回 None。
        调用时机：把用户消息存库之后、送给模型之前。
        """
        conv = self.get_conversation()
        uncompressed = self._load_uncompressed()

        # 滑动窗口内的最近 N 轮必须原样保留，只有「溢出窗口」的老消息才值得压缩
        keep_count = SLIDING_WINDOW_ROUNDS * 2
        if len(uncompressed) <= keep_count:
            return None

        overflow = uncompressed[:-keep_count]
        if len(overflow) < COMPRESS_TRIGGER:
            return None

        dialogue = "\n".join(
            f"{'用户' if m['role'] == 'user' else 'AI'}：{m['content']}" for m in overflow
        )
        if len(dialogue) > MAX_SUMMARY_INPUT_CHARS:
            dialogue = dialogue[-MAX_SUMMARY_INPUT_CHARS:]  # 超长就只保留最近的部分

        new_summary = await llm.summarize(conv.get("summary"), dialogue)
        last_id = overflow[-1]["id"]

        execute(
            "UPDATE conversations SET summary = %s, summary_upto_id = %s WHERE id = %s",
            (new_summary, last_id, self.conversation_id),
        )
        return new_summary

    # ========================================================
    # 组装送给模型的消息
    # ========================================================
    def build_system_prompt(self, base_prompt: str) -> str:
        """把历史摘要拼进系统提示词。"""
        conv = self.get_conversation()
        summary = (conv.get("summary") or "").strip()
        if not summary:
            return base_prompt
        return f"{base_prompt}\n\n{SUMMARY_BLOCK_HEADER}{summary}"

    def build_history(self) -> list[BaseMessage]:
        """
        返回 LangChain 消息列表：只包含滑动窗口内的最近 N 轮原始消息，
        最后一条就是刚刚存进去的用户提问（MessagesPlaceholder 的入参）。
        """
        messages: list[BaseMessage] = []
        for row in self._load_uncompressed():
            if row["role"] == "user":
                messages.append(HumanMessage(content=row["content"]))
            elif row["role"] == "assistant":
                messages.append(AIMessage(content=row["content"]))
            else:
                messages.append(SystemMessage(content=row["content"]))
        return messages

    def load_full_history(self) -> list[dict]:
        """给前端回显用的完整历史（含已被压缩的老消息，全部从库里读）。"""
        return query_all(
            """
            SELECT id, role, content, created_at
            FROM chat_history
            WHERE conversation_id = %s
            ORDER BY id ASC
            """,
            (self.conversation_id,),
        )

    # ========================================================
    # 给前端的「记忆状态」面板
    # ========================================================
    def status(self) -> dict:
        conv = self.get_conversation()
        total = query_one(
            "SELECT COUNT(*) AS c FROM chat_history WHERE conversation_id = %s",
            (self.conversation_id,),
        )["c"]
        uncompressed = self._load_uncompressed()
        compressed = total - len(uncompressed)
        window_limit = SLIDING_WINDOW_ROUNDS * 2

        return {
            "conversation_id": self.conversation_id,
            "total_messages": total,
            "compressed_messages": compressed,
            "uncompressed_messages": len(uncompressed),
            "window_rounds": SLIDING_WINDOW_ROUNDS,
            "window_messages": min(len(uncompressed), window_limit),
            "compress_trigger": COMPRESS_TRIGGER,
            "summary": conv.get("summary") or "",
            "summary_upto_id": conv["summary_upto_id"],
        }


# ============================================================
# 会话的增删查（供路由层调用）
# ============================================================
def create_conversation(user_id: int, title: str = "新对话") -> int:
    conv_id, _ = execute(
        "INSERT INTO conversations (user_id, title) VALUES (%s, %s)",
        (user_id, title),
    )
    return conv_id


def list_conversations(user_id: int) -> list[dict]:
    return query_all(
        """
        SELECT c.id, c.title, c.created_at, c.updated_at,
               (SELECT COUNT(*) FROM chat_history h WHERE h.conversation_id = c.id) AS message_count
        FROM conversations c
        WHERE c.user_id = %s
        ORDER BY c.updated_at DESC
        """,
        (user_id,),
    )


def delete_conversation(user_id: int, conversation_id: int) -> int:
    _, rows = execute(
        "DELETE FROM conversations WHERE id = %s AND user_id = %s",
        (conversation_id, user_id),
    )
    return rows


def ensure_default_conversation(user_id: int) -> int:
    """没有会话时自动建一个。"""
    row = query_one(
        "SELECT id FROM conversations WHERE user_id = %s ORDER BY updated_at DESC LIMIT 1",
        (user_id,),
    )
    return row["id"] if row else create_conversation(user_id)
