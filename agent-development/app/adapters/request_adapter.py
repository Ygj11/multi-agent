from __future__ import annotations

"""外部请求到内部消息的适配逻辑。"""

from uuid import uuid4

from app.observability.logger import log_event, preview_text
from app.schemas.message import ChatRequest, InboundMessage


class RequestAdapter:
    """负责把 HTTP 请求转为 Agent Runtime 可处理的 InboundMessage。"""

    def adapt(self, request: ChatRequest) -> InboundMessage:
        """提取最后一条用户消息，生成 request_id、trace_id 和 session_key。"""
        user_messages = [message for message in request.messages if message.role == "user"]
        if not user_messages:
            raise ValueError("messages must contain at least one user message")

        # 1、获取原始信息
        original_query = user_messages[-1].content
        # 2、构建session_key
        session_key = self.build_session_key(
            tenant_id=request.tenant_id,
            channel=request.channel,
            user_id=request.user_id,
            session_id=request.session_id,
        )
        request_id = f"req_{uuid4().hex}"
        trace_id = f"trace_{uuid4().hex}"
        log_event(
            "session_key_created",
            session_key=session_key,
            user_id=request.user_id,
            tenant_id=request.tenant_id,
            node="request_adapter",
            message="Session key created",
            data={"channel": request.channel, "session_id": request.session_id},
        )
        log_event(
            "request_adapted",
            request_id=request_id,
            trace_id=trace_id,
            session_key=session_key,
            user_id=request.user_id,
            tenant_id=request.tenant_id,
            node="request_adapter",
            message="Request adapted to inbound message",
            data={"message_count": len(request.messages), "original_query_preview": preview_text(original_query)},
        )
        log_event(
            "original_query",
            request_id=request_id,
            trace_id=trace_id,
            session_key=session_key,
            user_id=request.user_id,
            tenant_id=request.tenant_id,
            node="request_adapter",
            message="Original query extracted",
            data={"original_query_preview": preview_text(original_query)},
        )
        return InboundMessage(
            request_id=request_id,
            trace_id=trace_id,
            tenant_id=request.tenant_id,
            channel=request.channel,
            user_id=request.user_id,
            session_id=request.session_id,
            session_key=session_key,
            original_query=original_query,
            messages=request.messages,
        )

    @staticmethod
    def build_session_key(tenant_id: str, channel: str, user_id: str, session_id: str) -> str:
        """按 TASK1.md 要求生成多用户、多会话隔离键。"""
        return f"{tenant_id}:{channel}:{user_id}:{session_id}"
