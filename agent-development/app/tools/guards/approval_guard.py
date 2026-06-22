from __future__ import annotations

"""Human approval guard for write-side tools."""

from app.auth.principal import Principal
from app.schemas.tool import ToolResult


class ToolApprovalGuard:
    """Convert write-side tool calls into pending approval payloads."""

    def __init__(self, executor) -> None:
        self.executor = executor

    def requires_approval(self, definition, tool_name: str) -> bool:
        return self.executor._requires_approval(definition, tool_name)

    def build_result(
        self,
        *,
        agent_name: str,
        tool_name: str,
        arguments: dict,
        definition,
        principal: Principal | None,
        auth_context: dict | None,
        session_key: str | None,
        request_id: str | None,
        trace_id: str | None,
    ) -> ToolResult:
        approval_payload = {
            "agent_name": agent_name,
            "tool_name": tool_name,
            "arguments": arguments,
            "operation_type": self.executor._operation_type(tool_name),
            "risk_level": "high",
            "reason": f"Tool {tool_name} is a write-side operation and requires human approval.",
            "session_key": session_key,
            "request_id": request_id,
            "trace_id": trace_id,
            "principal": principal.model_dump() if principal else None,
            "auth_context": auth_context,
            "resource_type": definition.resource_type,
            "resource_id": self.executor._resource_id(definition, arguments),
            "required_scopes": definition.required_scopes,
            "approval_policy_id": getattr(getattr(definition, "contract", None), "approval_policy_id", None),
        }
        pending_tool_call = {
            "name": tool_name,
            "arguments": arguments,
            "agent_name": agent_name,
            "request_id": request_id,
            "trace_id": trace_id,
            "session_key": session_key,
        }
        return ToolResult(
            name=tool_name,
            agent_name=agent_name,
            allowed=False,
            success=False,
            error="human_approval_required",
            needs_human_approval=True,
            approval_payload=approval_payload,
            pending_tool_call=pending_tool_call,
        )
