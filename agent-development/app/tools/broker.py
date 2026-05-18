from __future__ import annotations

"""工具执行代理。"""

from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from app.observability.logger import log_event, preview_text
from app.schemas.tool import ToolCall, ToolResult
from app.tools.audit_store import ToolCallLogStore
from app.tools.policy_gate import PolicyGate
from app.tools.registry import ToolRegistry


class ToolBroker:
    """统一承接工具调用，强制经过 PolicyGate。"""

    def __init__(
        self,
        registry: ToolRegistry,
        policy_gate: PolicyGate,
        audit_store: ToolCallLogStore | None = None,
    ) -> None:
        """注入工具注册表和策略门。"""
        self.registry = registry
        self.policy_gate = policy_gate
        self.audit_store = audit_store

    async def call(self, call: ToolCall) -> ToolResult:
        """校验工具存在性、权限并标准化执行结果。"""
        started_perf = perf_counter()
        started_at = self._now()
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
            await self._write_audit(call, result, started_perf, started_at)
            self._log_finished(call, result, started_perf, level="WARNING")
            return result

        allowed, reason = await self.policy_gate.allow(call)
        if not allowed:
            result = ToolResult(name=call.name, allowed=False, success=False, error=reason)
            await self._write_audit(call, result, started_perf, started_at)
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
            await self._write_audit(call, result, started_perf, started_at)
            self._log_finished(call, result, started_perf)
            return result
        except Exception as exc:
            result = ToolResult(name=call.name, allowed=True, success=False, error=str(exc))
            await self._write_audit(call, result, started_perf, started_at)
            self._log_finished(call, result, started_perf, level="ERROR")
            return result

    async def _write_audit(
        self,
        call: ToolCall,
        result: ToolResult,
        started_perf: float,
        started_at: str,
    ) -> None:
        """写入工具调用审计；审计失败不影响主流程。"""
        if self.audit_store is None:
            return
        finished_at = self._now()
        duration_ms = max(0, int((perf_counter() - started_perf) * 1000))
        try:
            await self.audit_store.append(
                request_id=call.request_id,
                trace_id=call.trace_id,
                session_key=call.session_key,
                tool_name=call.name,
                arguments=call.arguments,
                allowed=result.allowed,
                success=result.success,
                result=result.result,
                error=result.error,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                created_at=finished_at,
            )
        except Exception:
            return

    @staticmethod
    def _now() -> str:
        """返回 UTC ISO 时间。"""
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _log_finished(call: ToolCall, result: ToolResult, started_perf: float, level: str = "INFO") -> None:
        """记录工具调用结束。"""
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
