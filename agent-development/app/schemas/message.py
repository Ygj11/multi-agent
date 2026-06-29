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
    """
    审批中断时，该 URL 会进入 resume_state
    审批 callback 恢复执行完成后，如果已经到终态，会 POST 最终结果到该 URL
    如果恢复后又触发下一轮审批，不会提前回调
    回调失败不会影响审批恢复结果，会记录到审批 result 和 approval_events
    """
    result_callback_url: str | None = None


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
    auth_context: dict[str, Any] | None = None
    result_callback_url: str | None = None


class ChatResponse(BaseModel):
    """POST /api/chat 的响应体。"""

    request_id: str
    session_key: str
    original_query: str
    rewritten_query: str
    intent: str
    answer: str
    approval_required: bool = False
    approval_id: str | None = None
    approval_status: str | None = None
