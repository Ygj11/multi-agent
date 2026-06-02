from __future__ import annotations

"""Card-driven tool executor."""

from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from app.observability.logger import log_event, preview_text
from app.auth.authorization_service import AuthorizationService, ResourceAccessService
from app.auth.principal import Principal
from app.evidence.builder import EvidenceBuilder
from app.evidence.store import EvidenceStore
from app.mcp.errors import MCPServerUnavailableError, MCPToolError, MCPToolTimeoutError
from app.schemas.agent_card import AgentCard
from app.approval.store import SQLiteApprovalStore
from app.schemas.tool import ToolResult
from app.tools.execution_pipeline import ToolExecutionContext, ToolExecutionPipeline
from app.tools.tool_execution_log_store import ToolExecutionLogStore
from app.tools.registry import ToolRegistry
from app.verification.schemas import VerificationInput
from app.verification.service import VerificationService
import json


class ToolExecutor:
    """Executes tools after checking AgentCard-based availability."""

    def __init__(
        self,
        registry: ToolRegistry,
        log_store: ToolExecutionLogStore | None = None,
        mcp_client_manager=None,
        approval_store: SQLiteApprovalStore | None = None,
        write_idempotency_enabled: bool = True,
        authorization_service: AuthorizationService | None = None,
        resource_access_service: ResourceAccessService | None = None,
        verification_service: VerificationService | None = None,
        evidence_store: EvidenceStore | None = None,
    ) -> None:
        self.registry = registry
        self.log_store = log_store
        self.mcp_client_manager = mcp_client_manager
        self.approval_store = approval_store
        self.write_idempotency_enabled = write_idempotency_enabled
        self.authorization_service = authorization_service
        self.resource_access_service = resource_access_service
        self.verification_service = verification_service
        self.evidence_store = evidence_store

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
        principal: dict[str, Any] | Principal | None = None,
        auth_context: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> ToolResult:
        started_perf = perf_counter()
        started_at = self._now()
        result = await ToolExecutionPipeline(self).run(
            ToolExecutionContext(
                agent_name=agent_name,
                tool_name=tool_name,
                arguments=arguments,
                agent_card=agent_card,
                request_id=request_id,
                trace_id=trace_id,
                session_key=session_key,
                principal=principal,
                auth_context=auth_context,
                evidence=evidence,
            )
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
        principal: dict[str, Any] | Principal | None = None,
        auth_context: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
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

        previous_success = await self._find_successful_approval_execution(approval_id) if self.write_idempotency_enabled else None
        if previous_success is not None:
            result = ToolResult(
                name=tool_name,
                agent_name=agent_name,
                allowed=True,
                success=True,
                result={
                    "skipped": True,
                    "reason": "idempotent_replay",
                    "previous_result": previous_success.get("result"),
                    "previous_log_id": previous_success.get("id"),
                },
                approval_id=approval_id,
            )
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

        principal_obj = self._coerce_principal(principal)
        auth_result = await self._authorize(
            definition=definition,
            principal=principal_obj,
            arguments=arguments,
            action=str(getattr(definition, "operation", "write")),
            approval_id=approval_id,
        )
        if auth_result is not None:
            await self._log(auth_result, arguments, request_id, trace_id, session_key, started_at, started_perf, approval_id=approval_id)
            return auth_result

        verification_result = await self._verify_pre_tool(
            agent_name=agent_name,
            tool_name=tool_name,
            arguments=arguments,
            request_id=request_id,
            trace_id=trace_id,
            session_key=session_key,
            principal=principal_obj,
            auth_context=auth_context,
            evidence=evidence or [],
            approval_id=approval_id,
        )
        if verification_result is not None:
            await self._log(verification_result, arguments, request_id, trace_id, session_key, started_at, started_perf, approval_id=approval_id)
            return verification_result

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
        if self.evidence_store is not None and session_key:
            try:
                evidence = EvidenceBuilder.from_tool_result(
                    session_key=session_key,
                    request_id=request_id,
                    trace_id=trace_id,
                    tool_name=result.name,
                    result=result.model_dump(),
                    summary=preview_text(str(result.result)) if result.result is not None else result.error,
                )
                await self.evidence_store.save(evidence)
            except Exception as exc:
                log_event(
                    "evidence_save_failed",
                    request_id=request_id,
                    trace_id=trace_id,
                    session_key=session_key,
                    node="tool_executor",
                    message="Tool evidence save failed",
                    data={"tool_name": result.name, "error": str(exc)},
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

    async def _authorize(
        self,
        *,
        definition,
        principal: Principal | None,
        arguments: dict[str, Any],
        action: str,
        approval_id: str | None = None,
    ) -> ToolResult | None:
        if self.authorization_service is not None:
            decision = self.authorization_service.check_tool_access(principal=principal, tool_definition=definition)
            if not decision.allowed:
                return ToolResult(
                    name=definition.name,
                    agent_name=definition.agent_name,
                    allowed=False,
                    success=False,
                    error=f"permission_denied:{decision.reason or 'tool_access'}",
                    approval_id=approval_id,
                )
        if self.resource_access_service is not None and definition.resource_type:
            decision = await self.resource_access_service.check_access(
                principal=principal,
                resource_type=definition.resource_type,
                resource_id=self._resource_id(definition, arguments),
                action=action,
            )
            if not decision.allowed:
                return ToolResult(
                    name=definition.name,
                    agent_name=definition.agent_name,
                    allowed=False,
                    success=False,
                    error=f"permission_denied:{decision.reason or 'resource_access'}",
                    approval_id=approval_id,
                )
        return None

    async def _verify_pre_tool(
        self,
        *,
        agent_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        request_id: str | None,
        trace_id: str | None,
        session_key: str | None,
        principal: Principal | None,
        auth_context: dict[str, Any] | None,
        evidence: list[dict[str, Any]],
        approval_id: str | None = None,
    ) -> ToolResult | None:
        if self.verification_service is None:
            return None
        verification = await self.verification_service.verify(
            VerificationInput(
                stage="pre_tool",
                request_id=request_id,
                trace_id=trace_id,
                session_key=session_key,
                principal=principal.model_dump() if principal else None,
                auth_context=auth_context or {},
                agent_name=agent_name,
                tool_name=tool_name,
                tool_arguments=arguments,
                evidence=evidence,
            )
        )
        if verification.action in {"block", "manual"} or not verification.passed:
            return ToolResult(
                name=tool_name,
                agent_name=agent_name,
                allowed=False,
                success=False,
                error=f"verification_failed:{verification.code or verification.reason or 'pre_tool'}",
                approval_id=approval_id,
            )
        return None

    @staticmethod
    def _coerce_principal(value: dict[str, Any] | Principal | None) -> Principal | None:
        if isinstance(value, Principal):
            return value
        if isinstance(value, dict):
            try:
                return Principal(**value)
            except Exception:
                return None
        return None

    @staticmethod
    def _resource_id(definition, arguments: dict[str, Any]) -> str | None:
        arg_name = getattr(definition, "resource_id_arg", None)
        if not arg_name:
            return None
        value = arguments.get(arg_name)
        return str(value) if value is not None else None

    async def _find_successful_approval_execution(self, approval_id: str) -> dict[str, Any] | None:
        if self.log_store is None:
            return None
        finder = getattr(self.log_store, "find_success_by_approval", None)
        if finder is None:
            return None
        return await finder(approval_id)

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
