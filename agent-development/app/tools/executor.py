from __future__ import annotations

"""Card-driven tool executor."""

import asyncio
import inspect
import json
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
from app.schemas.enums.observability import RuntimeEvent
from app.schemas.enums.tool import RiskLevel, ToolOperation, ToolSource, UnknownMCPToolPolicy
from app.schemas.enums.verification import VerificationAction, VerificationStage
from app.approval.store import SQLiteApprovalStore
from app.schemas.tool import ToolResult
from app.tools.error_codes import (
    MCP_SERVER_UNAVAILABLE,
    MCP_TOOL_ERROR,
    MCP_TOOL_POLICY_DENIED,
    MCP_TOOL_TIMEOUT,
    TOOL_EXECUTION_EXCEPTION,
    TOOL_RESULT_SCHEMA_INVALID,
    TOOL_TIMEOUT,
)
from app.tools.execution_pipeline import ToolExecutionContext, ToolExecutionPipeline
from app.tools.tool_execution_log_store import ToolExecutionLogStore
from app.tools.registry import ToolRegistry
from app.tools.result_schemas import validate_tool_result_schema
from app.verification.schemas import VerificationInput
from app.verification.service import VerificationService


class ToolExecutor:
    """工具真正执行前的安全边界。

    LLM 只能提出 tool call；ToolExecutor/ExecutionPipeline 决定它是否存在、
    是否对当前 Agent 可见、参数是否满足 schema、调用者是否有权限、是否需要
    pre-tool verification 或人工审批，最后才执行 local/MCP 工具。
    """

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
        unknown_mcp_tool_policy: str = str(UnknownMCPToolPolicy.ALLOW),
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
        self.unknown_mcp_tool_policy = self._normalize_unknown_mcp_tool_policy(unknown_mcp_tool_policy)

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
        """执行普通工具调用，统一经过 ToolExecutionPipeline 守卫链。"""
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
        # 日志打印和数据存储
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
        """执行已审批工具。

        审批通过不等于任意工具可执行：这里仍会校验 approval_id 对应的 Agent、
        tool_name 和 arguments 是否与当初申请完全一致，并继续执行权限与验证检查。

        与普通 execute() 的关键区别：
        - 普通路径在权限、验证之后如果发现需要审批，会返回 human_approval_required；
        - 审批恢复路径已经拿到了 approved 的 approval_id，因此不会再次调用
          _requires_approval() 创建新审批，否则会形成“审批通过后又申请审批”的死循环；
        - 但工具存在性、Agent 可见性、必填参数、principal 权限、资源访问、pre-tool
          verification 和幂等保护仍然必须重新检查，因为审批 callback 与原请求之间存在时间差。
        """
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
                missing_required_arguments=missing_arguments,
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
            principal=principal_obj,
            auth_context=auth_context,
        )
        result.approval_id = approval_id
        await self._log(result, arguments, request_id, trace_id, session_key, started_at, started_perf, approval_id=approval_id)
        return result

    async def _execute_definition(
        self,
        *,
        definition,
        agent_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        principal: Principal | None = None,
        auth_context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """调用已通过守卫的 ToolDefinition，并做超时和结果 schema 校验。"""
        try:
            raw = await asyncio.wait_for(
                self._invoke_definition(
                    definition=definition,
                    arguments=arguments,
                    principal=principal,
                    auth_context=auth_context,
                    tool_name=tool_name,
                ),
                timeout=self._tool_timeout_seconds(definition),
            )
            result = self._result_from_raw(
                definition=definition,
                agent_name=agent_name,
                tool_name=tool_name,
                raw=raw,
            )
            if result.success:
                """从 tooldefinition.contract 中获取工具定义的contract.result_schema
                contract 是 tool_contracts.yaml 配置驱动的，它为已注册 ToolDefinition 补充信息
                具体看contracts.py
                """
                schema_error = validate_tool_result_schema(self._result_schema(definition), raw)
                if schema_error:
                    result = ToolResult(
                        name=tool_name,
                        agent_name=agent_name,
                        allowed=True,
                        success=False,
                        error=TOOL_RESULT_SCHEMA_INVALID,
                        result={"detail": schema_error},
                    )
        except asyncio.TimeoutError as exc:
            error_code = MCP_TOOL_TIMEOUT if getattr(definition, "source", None) == ToolSource.MCP else TOOL_TIMEOUT
            result = ToolResult(name=tool_name, agent_name=agent_name, allowed=True, success=False, error=error_code)
            result.result = {"detail": str(exc) or error_code}
        except MCPServerUnavailableError as exc:
            result = ToolResult(name=tool_name, agent_name=agent_name, allowed=True, success=False, error=MCP_SERVER_UNAVAILABLE)
            result.result = {"detail": str(exc)}
        except MCPToolTimeoutError as exc:
            result = ToolResult(name=tool_name, agent_name=agent_name, allowed=True, success=False, error=MCP_TOOL_TIMEOUT)
            result.result = {"detail": str(exc)}
        except MCPToolError as exc:
            result = ToolResult(name=tool_name, agent_name=agent_name, allowed=True, success=False, error=MCP_TOOL_ERROR)
            result.result = {"detail": str(exc)}
        except Exception as exc:
            result = ToolResult(name=tool_name, agent_name=agent_name, allowed=True, success=False, error=TOOL_EXECUTION_EXCEPTION)
            result.result = {"detail": str(exc)}

        return result

    async def _invoke_definition(
        self,
        *,
        definition,
        arguments: dict[str, Any],
        principal: Principal | None,
        auth_context: dict[str, Any] | None,
        tool_name: str,
    ) -> Any:
        """根据 ToolDefinition source 分发到 MCP 或本地 callable。"""
        if definition.source == ToolSource.MCP:
            if self.mcp_client_manager is None:
                raise MCPServerUnavailableError("mcp_client_manager_not_configured")
            # MCP 工具调用链路：
            # 1. 启动或刷新 MCP server 时，ToolRegistry 会把 server 返回的原始工具
            #    注册成项目内规范名，例如 mcp.workflow.query_refund_task；
            # 2. LLM 只看到这个规范注册名，并按 OpenAI function calling 格式生成 tool call；
            # 3. ToolExecutor 先完成工具存在性、Agent 可见性、参数、权限、审批等确定性校验；
            # 4. MCPClientManager 再用规范注册名找到所属 server 和 server 原始工具名；
            # 5. MCP client 调用 server 的 tools/call，由 server 执行真实工具；
            # 6. server 返回结果后，ToolExecutor 会统一包装成 ToolResult 并写日志/evidence。
            return await self.mcp_client_manager.call_tool(tool_name, arguments)
        return await definition.callable(**self._call_arguments(definition, arguments, principal, auth_context))

    @staticmethod
    def _result_from_raw(*, definition, agent_name: str, tool_name: str, raw: Any) -> ToolResult:
        success = not (isinstance(raw, dict) and raw.get("success") is False)
        return ToolResult(
            name=tool_name,
            agent_name=agent_name,
            allowed=True,
            success=success,
            result=raw,
            error=str(raw.get("error")) if isinstance(raw, dict) and raw.get("success") is False else None,
        )

    @staticmethod
    def _tool_timeout_seconds(definition) -> float:
        contract = getattr(definition, "contract", None)
        timeout_ms = getattr(contract, "timeout_ms", None) or 10000
        return max(0.001, float(timeout_ms) / 1000.0)

    @staticmethod
    def _result_schema(definition) -> str | None:
        contract = getattr(definition, "contract", None)
        return getattr(contract, "result_schema", None)

    @staticmethod
    def _call_arguments(
        definition,
        arguments: dict[str, Any],
        principal: Principal | None,
        auth_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        call_args = dict(arguments)
        try:
            signature = inspect.signature(definition.callable)
        except (TypeError, ValueError):
            return call_args
        parameters = signature.parameters
        if "principal" in parameters:
            call_args["principal"] = principal
        if "auth_context" in parameters:
            call_args["auth_context"] = auth_context
        return call_args

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
        """三件事
        计算工具耗时 duration_ms，写回 ToolResult.duration_ms。
        打结构化运行日志 tool_execution_finished。
        如果配置了 store：
            写 tool_execution_logs：工具执行流水账。
            写 evidence：从工具结果抽取一份可供 Verify / Repair / 审计引用的证据。
                evidence中不保存完整的工具ToolResult，只保存摘要和 tool_log_id，完整事实回查 tool_execution_logs。
        """
        duration_ms = max(0, int((perf_counter() - started_perf) * 1000))
        result.duration_ms = duration_ms
        finished_at = self._now()
        log_event(
            RuntimeEvent.TOOL_EXECUTION_FINISHED,
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
        tool_log_id: int | None = None
        if self.log_store is not None:
            definition = self.registry.get_definition(result.name)
            tool_log_id = await self.log_store.append(
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
                source=str(definition.source) if definition else None,
                server_name=definition.server_name if definition else None,
                approval_id=approval_id or result.approval_id,
            )
        if self.evidence_store is not None and session_key and tool_log_id is not None:
            try:
                evidence = EvidenceBuilder.from_tool_result(
                    session_key=session_key,
                    request_id=request_id,
                    trace_id=trace_id,
                    tool_name=result.name,
                    result=result.model_dump(),
                    tool_log_id=tool_log_id,
                    summary=preview_text(str(result.result)) if result.result is not None else result.error,
                )
                await self.evidence_store.save(evidence)
            except Exception as exc:
                log_event(
                    RuntimeEvent.EVIDENCE_SAVE_FAILED,
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
        """只校验 required 参数存在性；完整业务含义仍由工具或后续任务治理。"""
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
        """执行工具级和资源级授权检查。

        ToolDefinition.required_scopes 用于工具级 scope 校验；
        ToolDefinition.resource_type/resource_id_arg 用于资源级访问校验。
        `action` 来自 ToolDefinition.operation，当前本地 ResourceAccessService
        只做资源 allowlist 判断，尚未按 action 分支；保留该参数是为了后续接入
        企业权限中心时能区分 read/write/delete/notify 等资源动作。
        """
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
                stage=VerificationStage.PRE_TOOL,
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
        if verification.action in {VerificationAction.BLOCK, VerificationAction.MANUAL} or not verification.passed:
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

    def _mcp_policy_denial(self, *, definition, agent_name: str, tool_name: str) -> ToolResult | None:
        """按未知 MCP 工具策略拒绝没有显式风险/操作声明的 MCP 工具。"""
        if getattr(definition, "source", None) != ToolSource.MCP:
            return None
        if self._mcp_unknown_policy_action(definition) is not UnknownMCPToolPolicy.DENY:
            return None
        return ToolResult(
            name=tool_name,
            agent_name=agent_name,
            allowed=False,
            success=False,
            error=MCP_TOOL_POLICY_DENIED,
            result={"policy": str(self.unknown_mcp_tool_policy), "reason": "unknown_mcp_tool_policy"},
        )

    def _requires_approval(self, definition, tool_name: str) -> bool:
        """集中判断工具是否需要人工审批。
        1、
        approval_policy_id 来自 app/tools/tool_contracts.yaml，通过 ToolContractCatalog 加载，
        再由 ToolRegistry._with_contract() 挂到 ToolDefinition.contract 上。当前 yaml 里还没有实际配置这个字段
        它的意义不是“是否写操作”，而是“走哪套审批策略”。比如以后接公司审批中心，可能不同工具走不同审批流。

        2、
        operation = definition.operation
        risk_level = definition.risk_level
        来源：（1）工具注册时定义，register_private(... operation="notify", risk_level="high")；（2）tool_contracts.yaml

        3、
        动态发现的 MCP 工具风险未知，MCP server 返回的工具没有明确声明：
        系统不知道这个 MCP 工具是不是写操作、高风险操作、DDL 操作
        由配置控制，UNKNOWN_MCP_TOOL_POLICY=allow|approval|deny，执行，审批，拒绝

        """
        contract = getattr(definition, "contract", None)
        if getattr(contract, "approval_policy_id", None):
            return True
        operation = getattr(definition, "operation", None)
        risk_level = getattr(definition, "risk_level", None)
        if getattr(definition, "source", None) == ToolSource.MCP and self._mcp_unknown_policy_action(definition) is UnknownMCPToolPolicy.APPROVAL:
            return True
        return bool(getattr(definition, "is_write", False)) or operation in {
            ToolOperation.WRITE,
            ToolOperation.NOTIFY,
            ToolOperation.DELETE,
            ToolOperation.DDL,
        } or risk_level is RiskLevel.HIGH

    def _mcp_unknown_policy_action(self, definition) -> UnknownMCPToolPolicy:
        if getattr(definition, "source", None) != ToolSource.MCP:
            return UnknownMCPToolPolicy.ALLOW
        if self._mcp_has_explicit_execution_policy(definition):
            return UnknownMCPToolPolicy.ALLOW
        return self.unknown_mcp_tool_policy

    @staticmethod
    def _mcp_has_explicit_execution_policy(definition) -> bool:
        contract = getattr(definition, "contract", None)
        metadata = getattr(definition, "metadata", None) or {}
        return bool(
            metadata.get("mcp_operation_defined")
            or metadata.get("mcp_risk_level_defined")
            or metadata.get("contract_operation_defined")
            or metadata.get("contract_risk_level_defined")
            or getattr(contract, "approval_policy_id", None)
        )

    @staticmethod
    def _normalize_unknown_mcp_tool_policy(value: str) -> UnknownMCPToolPolicy:
        policy = (value or str(UnknownMCPToolPolicy.ALLOW)).strip().lower()
        try:
            return UnknownMCPToolPolicy(policy)
        except ValueError as exc:
            raise ValueError("UNKNOWN_MCP_TOOL_POLICY must be one of: allow, approval, deny") from exc

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
