from __future__ import annotations

"""Card-driven tool executor."""

from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from app.observability.logger import log_event, preview_text
from app.mcp.errors import MCPServerUnavailableError, MCPToolError, MCPToolTimeoutError
from app.schemas.agent_card import AgentCard
from app.approval.store import SQLiteApprovalStore
from app.schemas.tool import ToolResult
from app.tools.tool_execution_log_store import ToolExecutionLogStore
from app.tools.registry import ToolRegistry
import json


class ToolExecutor:
    """Executes tools after checking AgentCard-based availability."""

    def __init__(
        self,
        registry: ToolRegistry,
        log_store: ToolExecutionLogStore | None = None,
        mcp_client_manager=None,
        approval_store: SQLiteApprovalStore | None = None,
    ) -> None:
        self.registry = registry
        self.log_store = log_store
        self.mcp_client_manager = mcp_client_manager
        self.approval_store = approval_store

    async def execute(
        self,
        *,
        agent_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        agent_card: AgentCard | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        session_key: str | None = None,
    ) -> ToolResult:
        started_perf = perf_counter()
        started_at = self._now()
        definition = self.registry.get_definition(tool_name)

        if definition is None:
            result = ToolResult(name=tool_name, agent_name=agent_name, allowed=False, success=False, error="tool_not_found")
            await self._log(result, arguments, request_id, trace_id, session_key, started_at, started_perf)
            return result

        if not self.registry.is_tool_available_for_agent(agent_name, tool_name, agent_card):
            result = ToolResult(
                name=tool_name,
                agent_name=agent_name,
                allowed=False,
                success=False,
                error="tool_not_available_for_agent",
            )
            await self._log(result, arguments, request_id, trace_id, session_key, started_at, started_perf)
            return result

        missing_arguments = self._missing_required_arguments(tool_name, arguments)
        if missing_arguments:
            result = ToolResult(
                name=tool_name,
                agent_name=agent_name,
                allowed=True,
                success=False,
                error=f"missing_required_argument:{','.join(missing_arguments)}",
            )
            await self._log(result, arguments, request_id, trace_id, session_key, started_at, started_perf)
            return result

        if self._requires_approval(definition, tool_name):
            approval_payload = {
                "agent_name": agent_name,
                "tool_name": tool_name,
                "arguments": arguments,
                "operation_type": self._operation_type(tool_name),
                "risk_level": "high",
                "reason": f"Tool {tool_name} is a write-side operation and requires human approval.",
                "session_key": session_key,
                "request_id": request_id,
                "trace_id": trace_id,
            }
            pending_tool_call = {
                "name": tool_name,
                "arguments": arguments,
                "agent_name": agent_name,
                "request_id": request_id,
                "trace_id": trace_id,
                "session_key": session_key,
            }
            result = ToolResult(
                name=tool_name,
                agent_name=agent_name,
                allowed=False,
                success=False,
                error="human_approval_required",
                needs_human_approval=True,
                approval_payload=approval_payload,
                pending_tool_call=pending_tool_call,
            )
            await self._log(result, arguments, request_id, trace_id, session_key, started_at, started_perf)
            return result

        result = await self._execute_definition(
            definition=definition,
            agent_name=agent_name,
            tool_name=tool_name,
            arguments=arguments,
        )
        await self._log(result, arguments, request_id, trace_id, session_key, started_at, started_perf)
        return result

    async def execute_approved_tool(
        self,
        *,
        approval_id: str,
        agent_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        session_key: str,
        request_id: str,
        trace_id: str | None,
        agent_card: AgentCard | None = None,
    ) -> ToolResult:
        """Execute one approved write tool after validating it matches the stored approval."""
        started_perf = perf_counter()
        started_at = self._now()
        if self.approval_store is None:
            result = ToolResult(name=tool_name, agent_name=agent_name, allowed=False, success=False, error="approval_store_not_configured", approval_id=approval_id)
            await self._log(result, arguments, request_id, trace_id, session_key, started_at, started_perf, approval_id=approval_id)
            return result

        approval = await self.approval_store.get(approval_id)
        error = self._validate_approved_tool_request(
            approval=approval,
            agent_name=agent_name,
            tool_name=tool_name,
            arguments=arguments,
        )
        if error:
            result = ToolResult(name=tool_name, agent_name=agent_name, allowed=False, success=False, error=error, approval_id=approval_id)
            await self._log(result, arguments, request_id, trace_id, session_key, started_at, started_perf, approval_id=approval_id)
            return result

        definition = self.registry.get_definition(tool_name)
        if definition is None:
            result = ToolResult(name=tool_name, agent_name=agent_name, allowed=False, success=False, error="tool_not_found", approval_id=approval_id)
            await self._log(result, arguments, request_id, trace_id, session_key, started_at, started_perf, approval_id=approval_id)
            return result

        if not self.registry.is_tool_available_for_agent(agent_name, tool_name, agent_card):
            result = ToolResult(name=tool_name, agent_name=agent_name, allowed=False, success=False, error="tool_not_available_for_agent", approval_id=approval_id)
            await self._log(result, arguments, request_id, trace_id, session_key, started_at, started_perf, approval_id=approval_id)
            return result

        missing_arguments = self._missing_required_arguments(tool_name, arguments)
        if missing_arguments:
            result = ToolResult(
                name=tool_name,
                agent_name=agent_name,
                allowed=True,
                success=False,
                error=f"missing_required_argument:{','.join(missing_arguments)}",
                approval_id=approval_id,
            )
            await self._log(result, arguments, request_id, trace_id, session_key, started_at, started_perf, approval_id=approval_id)
            return result

        result = await self._execute_definition(
            definition=definition,
            agent_name=agent_name,
            tool_name=tool_name,
            arguments=arguments,
        )
        result.approval_id = approval_id
        await self._log(result, arguments, request_id, trace_id, session_key, started_at, started_perf, approval_id=approval_id)
        return result

    async def _execute_definition(self, *, definition, agent_name: str, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        try:
            if definition.source == "mcp":
                if self.mcp_client_manager is None:
                    raise MCPServerUnavailableError("mcp_client_manager_not_configured")
                raw = await self.mcp_client_manager.call_tool(tool_name, arguments)
            else:
                raw = await definition.callable(**arguments)
            success = not (isinstance(raw, dict) and raw.get("success") is False)
            result = ToolResult(
                name=tool_name,
                agent_name=agent_name,
                allowed=True,
                success=success,
                result=raw,
                error=str(raw.get("error")) if isinstance(raw, dict) and raw.get("success") is False else None,
            )
        except MCPServerUnavailableError as exc:
            result = ToolResult(name=tool_name, agent_name=agent_name, allowed=True, success=False, error="mcp_server_unavailable")
            result.result = {"detail": str(exc)}
        except MCPToolTimeoutError as exc:
            result = ToolResult(name=tool_name, agent_name=agent_name, allowed=True, success=False, error="mcp_tool_timeout")
            result.result = {"detail": str(exc)}
        except MCPToolError as exc:
            result = ToolResult(name=tool_name, agent_name=agent_name, allowed=True, success=False, error="mcp_tool_error")
            result.result = {"detail": str(exc)}
        except Exception as exc:
            result = ToolResult(name=tool_name, agent_name=agent_name, allowed=True, success=False, error=str(exc))

        return result

    async def _log(
        self,
        result: ToolResult,
        arguments: dict[str, Any],
        request_id: str | None,
        trace_id: str | None,
        session_key: str | None,
        started_at: str,
        started_perf: float,
        approval_id: str | None = None,
    ) -> None:
        duration_ms = max(0, int((perf_counter() - started_perf) * 1000))
        result.duration_ms = duration_ms
        finished_at = self._now()
        log_event(
            "tool_execution_finished",
            request_id=request_id,
            trace_id=trace_id,
            session_key=session_key,
            node="tool_executor",
            message="Tool execution finished",
            data={
                "agent_name": result.agent_name,
                "tool_name": result.name,
                "success": result.success,
                "error": result.error,
                "duration_ms": duration_ms,
                "source": self._definition_source(result.name),
                "approval_id": approval_id or result.approval_id,
                "result_preview": preview_text(str(result.result)) if result.result is not None else None,
            },
        )
        if self.log_store is not None:
            definition = self.registry.get_definition(result.name)
            await self.log_store.append(
                request_id=request_id,
                trace_id=trace_id,
                session_key=session_key,
                agent_name=result.agent_name or "unknown",
                tool_name=result.name,
                arguments=arguments,
                success=result.success,
                result=result.result,
                error=result.error,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                source=definition.source if definition else None,
                server_name=definition.server_name if definition else None,
                original_tool_name=definition.original_name if definition else None,
                approval_id=approval_id or result.approval_id,
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _definition_source(self, name: str) -> str | None:
        definition = self.registry.get_definition(name)
        return definition.source if definition else None

    def _missing_required_arguments(self, tool_name: str, arguments: dict[str, Any]) -> list[str]:
        required = self.registry.get_required_arguments(tool_name)
        return [name for name in required if name not in arguments or arguments.get(name) is None]

    @staticmethod
    def _operation_type(tool_name: str) -> str:
        lowered = tool_name.lower()
        for operation in ("delete", "update", "modify", "write", "create", "submit"):
            if operation in lowered:
                return operation
        return "write"

    @classmethod
    def _requires_approval(cls, definition, tool_name: str) -> bool:
        return bool(getattr(definition, "is_write", False))

    @classmethod
    def _validate_approved_tool_request(
        cls,
        *,
        approval,
        agent_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str | None:
        if approval is None:
            return "approval_not_found"
        if approval.status != "approved":
            return "approval_not_approved"
        if approval.agent_name != agent_name:
            return "approval_agent_mismatch"
        if approval.tool_name != tool_name:
            return "approval_tool_mismatch"
        if cls._canonical_json(approval.arguments) != cls._canonical_json(arguments):
            return "approval_arguments_mismatch"
        return None

    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
