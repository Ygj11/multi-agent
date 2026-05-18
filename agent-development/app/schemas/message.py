from __future__ import annotations

"""聊天 API 和内部消息 schema。"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """外部请求中的单条聊天消息。"""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    """POST /api/chat 的请求体。"""

    tenant_id: str
    channel: str
    user_id: str
    session_id: str
    messages: list[ChatMessage]


class InboundMessage(BaseModel):
    """RequestAdapter 产出的内部标准消息。"""

    request_id: str
    trace_id: str
    tenant_id: str
    channel: str
    user_id: str
    session_id: str
    session_key: str
    original_query: str
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    """POST /api/chat 的响应体。"""

    request_id: str
    session_key: str
    original_query: str
    rewritten_query: str
    intent: str
    answer: str
