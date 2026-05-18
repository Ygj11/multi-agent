from __future__ import annotations

"""内部状态到 HTTP 响应的适配逻辑。"""

from app.observability.logger import log_event, preview_text
from app.schemas.message import ChatResponse


class ResponseAdapter:
    """负责将 LangGraph 最终 state 转成对外 ChatResponse。"""

    def adapt(self, state: dict) -> ChatResponse:
        """只暴露验收要求的核心字段，避免泄漏内部运行时状态。"""
        log_event(
            "response_finalized",
            request_id=state.get("request_id"),
            trace_id=state.get("trace_id"),
            session_key=state.get("session_key"),
            user_id=state.get("user_id"),
            tenant_id=state.get("tenant_id"),
            node="response_adapter",
            message="Response finalized",
            data={"intent": state.get("intent"), "answer_preview": preview_text(state.get("answer", ""))},
        )
        return ChatResponse(
            request_id=state["request_id"],
            session_key=state["session_key"],
            original_query=state["original_query"],
            rewritten_query=state.get("rewritten_query") or state["original_query"],
            intent=state.get("intent") or "unknown",
            answer=state.get("answer") or "",
        )
