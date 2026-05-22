from __future__ import annotations

"""Card-driven tool executor."""

from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from app.observability.logger import log_event, preview_text
from app.mcp.errors import MCPServerUnavailableError, MCPToolError, MCPToolTimeoutError
from app.schemas.agent_card import AgentCard
from app.schemas.tool import ToolResult
from app.tools.audit_store import ToolExecutionLogStore
from app.tools.registry import ToolRegistry


class ToolExecutor:
    """Executes tools after checking AgentCard-based availability."""

    def __init__(
        self,
        registry: ToolRegistry,
        log_store: ToolExecutionLogStore | None = None,
        mcp_client_manager=None,
    ) -> None:
        self.registry = registry
        self.log_store = log_store
        self.mcp_client_manager = mcp_client_manager

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

        if definition.is_write:
            result = ToolResult(
                name=tool_name,
                agent_name=agent_name,
                allowed=False,
                success=False,
                error="human_approval_required",
            )
            await self._log(result, arguments, request_id, trace_id, session_key, started_at, started_perf)
            return result

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

        await self._log(result, arguments, request_id, trace_id, session_key, started_at, started_perf)
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
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _definition_source(self, name: str) -> str | None:
        definition = self.registry.get_definition(name)
        return definition.source if definition else None
