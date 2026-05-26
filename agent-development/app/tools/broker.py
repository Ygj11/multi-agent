from __future__ import annotations

"""Legacy direct tool broker.

The current /api/chat tool path is ToolCallingRunner -> ToolExecutor.
ToolBroker remains only for direct-tool compatibility tests and restricted
operational helpers; persistent audit is handled by ToolExecutor.
"""

from datetime import UTC, datetime
from time import perf_counter

from app.observability.logger import log_event, preview_text
from app.schemas.tool import ToolCall, ToolResult
from app.tools.policy_gate import PolicyGate
from app.tools.registry import ToolRegistry


class ToolBroker:
    """Execute direct tool calls after PolicyGate checks."""

    def __init__(
        self,
        registry: ToolRegistry,
        policy_gate: PolicyGate,
    ) -> None:
        self.registry = registry
        self.policy_gate = policy_gate

    async def call(self, call: ToolCall) -> ToolResult:
        """Validate tool existence and policy, then return a normalized result."""
        started_perf = perf_counter()
        log_event(
            "tool_call_requested",
            request_id=call.request_id,
            trace_id=call.trace_id,
            session_key=call.session_key,
            node="tool_broker",
            message="Tool call requested",
            data={"tool_name": call.name, "arguments_preview": call.arguments},
        )
        tool = self.registry.get(call.name)
        if tool is None:
            result = ToolResult(name=call.name, allowed=False, success=False, error="tool not found")
            self._log_finished(call, result, started_perf, level="WARNING")
            return result

        allowed, reason = await self.policy_gate.allow(call)
        if not allowed:
            result = ToolResult(name=call.name, allowed=False, success=False, error=reason)
            self._log_finished(call, result, started_perf, level="WARNING")
            return result

        try:
            log_event(
                "tool_call_started",
                request_id=call.request_id,
                trace_id=call.trace_id,
                session_key=call.session_key,
                node="tool_broker",
                message="Tool call started",
                data={"tool_name": call.name},
            )
            raw_result = await tool(**call.arguments)
            if isinstance(raw_result, dict) and raw_result.get("success") is False:
                result = ToolResult(
                    name=call.name,
                    allowed=True,
                    success=False,
                    result=raw_result,
                    error=str(raw_result.get("error") or "tool returned success=false"),
                )
            else:
                result = ToolResult(name=call.name, allowed=True, success=True, result=raw_result)
            self._log_finished(call, result, started_perf)
            return result
        except Exception as exc:
            result = ToolResult(name=call.name, allowed=True, success=False, error=str(exc))
            self._log_finished(call, result, started_perf, level="ERROR")
            return result

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _log_finished(call: ToolCall, result: ToolResult, started_perf: float, level: str = "INFO") -> None:
        duration_ms = max(0, int((perf_counter() - started_perf) * 1000))
        log_event(
            "tool_call_finished",
            level=level,
            request_id=call.request_id,
            trace_id=call.trace_id,
            session_key=call.session_key,
            node="tool_broker",
            message="Tool call finished",
            data={
                "tool_name": call.name,
                "allowed": result.allowed,
                "success": result.success,
                "error": result.error,
                "duration_ms": duration_ms,
                "result_preview": preview_text(str(result.result)) if result.result is not None else None,
            },
        )
