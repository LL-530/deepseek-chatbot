"""
llm.py —— 大模型客户端（Ollama 本地部署的 deepseek-r1:8b）
------------------------------------------------------------
对外提供：
    get_chat_model()            拿一个 ChatOllama 实例
    build_prompt()              带 MessagesPlaceholder 的对话模板
    stream_reply(history)       异步生成器，逐块吐出 思考 / 正文
    summarize(prev_summary, text)  调模型做摘要压缩
    check_model_ready()         启动时自检：模型在不在、服务通不通
"""
from __future__ import annotations

import re
from typing import AsyncGenerator, Iterable, Optional

import httpx
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_ollama import ChatOllama

from config import (
    LLM_MODEL,
    LLM_TEMPERATURE,
    NUM_CTX,
    OLLAMA_BASE_URL,
    SHOW_THINKING,
    SUMMARY_MODEL,
    SYSTEM_PROMPT,
)

# ============================================================
# 一、对话提示词模板（LangChain MessagesPlaceholder）
# ============================================================
# history 里按顺序放：滑动窗口内的最近 N 轮原始消息
# system_prompt 里会带上「历史摘要」，由 memory.ConversationMemory 动态拼好
CHAT_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "{system_prompt}"),
        MessagesPlaceholder(variable_name="history"),
    ]
)

SUMMARY_PROMPT = """你是一个对话摘要压缩器。请阅读下面的对话记录，输出一段简洁的中文摘要。

要求：
1. 必须保留的关键事实：用户的姓名/称呼、身份、喜好、经历、宠物、目标、已经确认的结论、待办事项。
   姓名、宠物名、颜色、数字这类具体信息要**原样照抄**，绝对不要改写、模糊化或省略。
2. 丢弃寒暄、重复内容和无关细节。
3. 用第三人称陈述，例如「用户的姓名是 X」「用户养了一只叫 Y 的猫」「已确认…」。
4. 只输出摘要正文，不要任何解释、标题或 Markdown 标记。
5. 控制在 {limit} 字以内。

{previous}
对话记录：
{dialogue}

摘要："""


# ============================================================
# 二、模型实例
# ============================================================
def get_chat_model(streaming: bool = True) -> ChatOllama:
    """对话模型（deepseek-r1:8b，跑在本机 Ollama 上）。"""
    return ChatOllama(
        model=LLM_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=LLM_TEMPERATURE,
        streaming=streaming,
        # 打开推理模型的原生思考链输出（deepseek-r1 支持），
        # 思考内容会出现在 chunk.additional_kwargs["reasoning_content"] 里
        reasoning=SHOW_THINKING,
        # 上下文窗口大小，配合滑动窗口使用（低配机器可在 .env 里调小）
        num_ctx=NUM_CTX,
    )


def get_summary_model() -> ChatOllama:
    """摘要模型。温度调低，保证压缩结果稳定。"""
    return ChatOllama(
        model=SUMMARY_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0.1,
        streaming=False,
        num_ctx=NUM_CTX,
    )


# ============================================================
# 三、流式对话
# ============================================================
def _split_inline_thinking(text: str) -> tuple[str, str]:
    """
    兜底解析：有些推理模型会把思考链以  thinking...<｜end▁of▁thinking｜> 的形式
    混在正文里，这里把它拆出来，避免直接显示给用户。
    """
    think_parts = re.findall(r" thinking(.*?)<｜end▁of▁thinking｜>", text, flags=re.S)
    clean = re.sub(r" thinking.*?<｜end▁of▁thinking｜>", "", text, flags=re.S)
    return "".join(think_parts).strip(), clean


async def stream_reply(
    history: Iterable[BaseMessage],
    system_prompt: str = SYSTEM_PROMPT,
) -> AsyncGenerator[tuple[str, str], None]:
    """
    把 history 交给模型，逐块 yield (kind, text)。
        kind = "thinking"  模型的思考链
        kind = "delta"     正式回答内容
    """
    model = get_chat_model(streaming=True)
    messages = CHAT_PROMPT.format_messages(system_prompt=system_prompt, history=list(history))

    async for chunk in model.astream(messages):
        # ---- 思考链：不同版本 LangChain/Ollama 放的字段名不一样，挨个试 ----
        reasoning = ""
        for key in ("reasoning_content", "thinking", "reasoning"):
            value = chunk.additional_kwargs.get(key)
            if value:
                reasoning += value
        if reasoning and SHOW_THINKING:
            yield "thinking", reasoning

        # ---- 正文 ----
        text = chunk.content or ""
        if not text:
            continue
        if isinstance(text, list):  # 少数版本 content 会是分段结构
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        if not text:
            continue

        inline_think, visible = _split_inline_thinking(text)
        if inline_think and SHOW_THINKING:
            yield "thinking", inline_think
        if visible:
            yield "delta", visible


# ============================================================
# 四、摘要压缩
# ============================================================
async def summarize(previous_summary: Optional[str], dialogue: str, limit: int = 300) -> str:
    """
    把「已有摘要 + 一批即将被丢弃的老消息」合并压缩成新的摘要。
    这是防止 token 爆炸的关键一步。
    """
    previous = f"已有摘要（请在此基础上合并更新）：\n{previous_summary}\n" if previous_summary else ""
    prompt = SUMMARY_PROMPT.format(limit=limit, previous=previous, dialogue=dialogue)

    model = get_summary_model()
    result = await model.ainvoke([HumanMessage(content=prompt)])
    text = result.content if isinstance(result.content, str) else str(result.content)

    _, visible = _split_inline_thinking(text)
    return (visible or text).strip()


# ============================================================
# 五、启动自检
# ============================================================
def check_model_ready() -> tuple[bool, str]:
    """检查 Ollama 服务是否在线、目标模型是否已下载。"""
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5.0)
        resp.raise_for_status()
        names = [m.get("name", "") for m in resp.json().get("models", [])]
    except Exception as exc:  # noqa: BLE001
        return False, f"无法连接 Ollama（{OLLAMA_BASE_URL}）：{exc}"

    if LLM_MODEL not in names:
        return False, f"Ollama 里没有找到模型「{LLM_MODEL}」。当前已有：{', '.join(names) or '（空）'}"
    return True, f"Ollama 就绪，使用模型 {LLM_MODEL}"
