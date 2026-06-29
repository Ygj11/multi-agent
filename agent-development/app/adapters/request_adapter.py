from __future__ import annotations

"""Adapt external chat requests to runtime messages."""

from uuid import uuid4

from app.auth.principal import AuthContext, Principal
from app.config.settings import get_settings
from app.observability.logger import log_event, preview_text
from app.schemas.enums.observability import RuntimeEvent
from app.schemas.message import ChatRequest, InboundMessage


class RequestAdapter:
    """将 HTTP ChatRequest 转为运行时 InboundMessage。

    可信身份来自 FastAPI dependency 解析出的 Principal。body fallback 只是本地
    开发兼容能力；关闭 ALLOW_REQUEST_BODY_IDENTITY_FALLBACK 后，必须提供可信
    Principal，不能用请求体里的 tenant/user 自证身份。
    """

    def adapt(self, request: ChatRequest, principal: Principal | None = None) -> InboundMessage:
        """Extract the last user message and build request/session identifiers."""
        user_messages = [message for message in request.messages if message.role == "user"]
        if not user_messages:
            raise ValueError("messages must contain at least one user message")

        original_query = user_messages[-1].content
        settings = get_settings()
        if principal is not None:
            if request.tenant_id != principal.tenant_id:
                raise PermissionError("request tenant_id does not match authenticated principal")
            if request.user_id != principal.effective_user_id and not settings.allow_request_body_identity_fallback:
                raise PermissionError("request user_id does not match authenticated principal")
            tenant_id = principal.tenant_id
            user_id = principal.effective_user_id
            auth_context = AuthContext(principal=principal, auth_source="dev_header")
        else:
            if not settings.allow_request_body_identity_fallback:
                raise PermissionError("authenticated principal required")
            tenant_id = request.tenant_id
            user_id = request.user_id
            fallback_principal = Principal(
                tenant_id=tenant_id,
                subject=user_id,
                user_id=user_id,
                channel=request.channel,
                scopes=["agent:use", "policy:read", "claim:read", "troubleshooting:read"],
                data_permissions=[],
            )
            auth_context = AuthContext(principal=fallback_principal, auth_source="body_fallback")

        session_key = self.build_session_key(
            tenant_id=tenant_id,
            channel=request.channel,
            user_id=user_id,
            session_id=request.session_id,
        )
        request_id = f"req_{uuid4().hex}"
        trace_id = f"trace_{uuid4().hex}"

        log_event(
            RuntimeEvent.REQUEST_ADAPTED,
            request_id=request_id,
            trace_id=trace_id,
            session_key=session_key,
            user_id=user_id,
            tenant_id=tenant_id,
            node="request_adapter",
            message="Request adapted to inbound message",
            data={
                "channel": request.channel,
                "session_id": request.session_id,
                "message_count": len(request.messages),
                "original_query_preview": preview_text(original_query),
                "auth_source": auth_context.auth_source,
            },
        )

        return InboundMessage(
            request_id=request_id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            channel=request.channel,
            user_id=user_id,
            session_id=request.session_id,
            session_key=session_key,
            original_query=original_query,
            messages=request.messages,
            auth_context=auth_context.model_dump(),
            result_callback_url=request.result_callback_url,
        )

    @staticmethod
    def build_session_key(tenant_id: str, channel: str, user_id: str, session_id: str) -> str:
        """Build a multi-tenant, multi-user session isolation key."""
        return f"{tenant_id}:{channel}:{user_id}:{session_id}"
