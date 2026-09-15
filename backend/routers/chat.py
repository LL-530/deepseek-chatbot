"""
routers/chat.py —— 流式聊天 + 会话/历史查询
------------------------------------------------------------
POST   /api/chat/stream                  流式对话（SSE，打字机效果）
GET    /api/conversations                会话列表
POST   /api/conversations                新建会话
DELETE /api/conversations/{id}           删除会话
GET    /api/conversations/{id}/messages  历史消息回显
GET    /api/conversations/{id}/memory    查看记忆状态（滑动窗口 / 摘要）
"""
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import llm
from auth import get_current_user
from config import SYSTEM_PROMPT
from memory import (
    ConversationMemory,
    ConversationNotFound,
    create_conversation,
    delete_conversation,
    list_conversations,
)

router = APIRouter(prefix="/api", tags=["聊天"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # 关掉 nginx 之类中间层的缓冲，保证真的逐字下发
}


def _sse(payload: dict) -> str:
    """把 dict 打包成一条 SSE 事件。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ============================================================
# 会话管理
# ============================================================
class ConversationCreateIn(BaseModel):
    title: str = Field("新对话", max_length=120)


@router.get("/conversations", summary="我的会话列表")
def get_conversations(user: dict = Depends(get_current_user)):
    items = list_conversations(user["id"])
    return {"total": len(items), "items": items}


@router.post("/conversations", status_code=201, summary="新建会话")
def new_conversation(body: ConversationCreateIn, user: dict = Depends(get_current_user)):
    conv_id = create_conversation(user["id"], body.title or "新对话")
    return {"id": conv_id, "title": body.title or "新对话"}


@router.delete("/conversations/{conversation_id}", summary="删除会话（连带聊天记录）")
def remove_conversation(conversation_id: int, user: dict = Depends(get_current_user)):
    if not delete_conversation(user["id"], conversation_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"message": "会话已删除"}


@router.get("/conversations/{conversation_id}/messages", summary="历史消息回显")
def get_messages(conversation_id: int, user: dict = Depends(get_current_user)):
    mem = ConversationMemory(user["id"], conversation_id)
    try:
        mem.get_conversation()
    except ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"conversation_id": conversation_id, "items": mem.load_full_history()}


@router.get("/conversations/{conversation_id}/memory", summary="查看记忆状态（滑动窗口/摘要）")
def get_memory_status(conversation_id: int, user: dict = Depends(get_current_user)):
    mem = ConversationMemory(user["id"], conversation_id)
    try:
        return mem.status()
    except ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ============================================================
# 流式对话
# ============================================================
class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000, description="用户这一轮说的话")
    conversation_id: int | None = Field(None, description="不传则自动新建/复用最近一个会话")


@router.post("/chat/stream", summary="流式对话（SSE）")
async def chat_stream(body: ChatIn, user: dict = Depends(get_current_user)):
    # ---- 1. 定位会话 ----
    if body.conversation_id:
        mem = ConversationMemory(user["id"], body.conversation_id)
        try:
            mem.get_conversation()
        except ConversationNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    else:
        conv_id = create_conversation(user["id"])
        mem = ConversationMemory(user["id"], conv_id)

    question = body.message.strip()

    # ---- 2. 先把用户消息落库（这样它自然成为滑动窗口的最后一条）----
    mem.touch_title(question)
    user_message_id = mem.add_message("user", question)

    async def event_stream() -> AsyncGenerator[str, None]:
        yield _sse(
            {
                "type": "meta",
                "conversation_id": mem.conversation_id,
                "user_message_id": user_message_id,
            }
        )

        buffer: list[str] = []
        try:
            # ---- 3. 该压缩就压缩（★ 防 token 爆炸）----
            new_summary = await mem.compress_if_needed()
            if new_summary is not None:
                yield _sse({"type": "compressed", "summary": new_summary, **mem.status()})

            # ---- 4. 组装 [历史摘要 + 最近 N 轮]，流式要答案 ----
            system_prompt = mem.build_system_prompt(SYSTEM_PROMPT)
            history = mem.build_history()

            async for kind, text in llm.stream_reply(history, system_prompt):
                yield _sse({"type": kind, "content": text})
                if kind == "delta":
                    buffer.append(text)

        except Exception as exc:  # noqa: BLE001
            yield _sse({"type": "error", "message": f"模型调用失败：{exc}"})

        # ---- 5. AI 回复落库 ----
        answer = "".join(buffer).strip()
        if answer:
            assistant_message_id = mem.add_message("assistant", answer)
        else:
            assistant_message_id = None

        yield _sse(
            {
                "type": "done",
                "conversation_id": mem.conversation_id,
                "message_id": assistant_message_id,
                "memory": mem.status(),
            }
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)
