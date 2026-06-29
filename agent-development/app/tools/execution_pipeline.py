from __future__ import annotations

"""普通工具调用的执行流水线。

Pipeline 把 ToolExecutor 的守卫顺序显式化，便于测试和审查。这里不做 LLM
推理，只处理一次已经归一化的 tool call。
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.auth.principal import Principal
from app.schemas.agent_card import AgentCard
from app.schemas.tool import ToolResult
from app.tools.guards.approval_guard import ToolApprovalGuard
from app.tools.guards.argument_guard import ToolArgumentGuard
from app.tools.guards.authorization_guard import ToolAuthorizationGuard
from app.tools.guards.availability_guard import ToolAvailabilityGuard
from app.tools.guards.verification_guard import ToolVerificationGuard

if TYPE_CHECKING:
    from app.tools.base import ToolDefinition
    from app.tools.executor import ToolExecutor


@dataclass(slots=True)
class ToolExecutionContext:
    """一次工具调用进入守卫链所需的上下文。"""

    agent_name: str
    tool_name: str
    arguments: dict[str, Any]
    agent_card: AgentCard | None = None
    request_id: str | None = None
    trace_id: str | None = None
    session_key: str | None = None
    principal: dict[str, Any] | Principal | None = None
    auth_context: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] | None = None


class ToolExecutionPipeline:
    """按固定顺序执行企业级工具守卫。"""

    def __init__(self, executor: ToolExecutor) -> None:
        self.executor = executor
        self.availability_guard = ToolAvailabilityGuard(executor.registry)
        self.argument_guard = ToolArgumentGuard(executor.registry)
        self.authorization_guard = ToolAuthorizationGuard(executor)
        self.verification_guard = ToolVerificationGuard(executor)
        self.approval_guard = ToolApprovalGuard(executor)

    async def run(self, context: ToolExecutionContext) -> ToolResult:
        """普通工具调用的守卫链。

        顺序很重要：
        1. 工具存在且对当前 Agent 可见；
        2. LLM 生成的参数满足工具 JSON Schema required；
        3. principal 具备 ToolDefinition.required_scopes；
        4. principal 可访问 resource_type/resource_id_arg 指向的业务资源；
        5. pre-tool verification 没有阻断；
        6. 未知 MCP 工具策略没有拒绝；
        7. 写操作/高风险/审批策略命中时返回 human_approval_required，不执行工具；
        8. 全部通过后才调用本地 callable 或 MCP 工具。
        """

        # 1. 工具必须存在，并且对当前 AgentCard 可见。
        definition, exists_error = self.availability_guard.check_exists(
            agent_name=context.agent_name,
            tool_name=context.tool_name,
        )
        if exists_error is not None:
            return exists_error

        visibility_error = self.availability_guard.check_visible(
            agent_name=context.agent_name,
            tool_name=context.tool_name,
            agent_card=context.agent_card,
        )
        if visibility_error is not None:
            return visibility_error

        # 2. LLM 可以提出工具调用，但系统必须先检查参数是否满足工具执行契约；
        # 不满足就把缺参错误作为 tool observation 返回给 LLM，让 LLM 有机会补参数或向用户澄清。
        missing_error = self.argument_guard.check_required(
            agent_name=context.agent_name,
            tool_name=context.tool_name,
            arguments=context.arguments,
        )
        if missing_error is not None:
            return missing_error

        # 3. 执行前权限检查：scope/resource 权限由确定性代码判断，不交给 LLM。
        principal_obj = self.executor._coerce_principal(context.principal)
        auth_error = await self.authorization_guard.check(
            definition=definition,
            principal=principal_obj,
            arguments=context.arguments,
            action=str(getattr(definition, "operation", "read")),
        )
        if auth_error is not None:
            return auth_error

        # 4. pre-tool verification 可根据当前工具、参数和证据做额外策略检查。
        verification_error = await self.verification_guard.check(
            agent_name=context.agent_name,
            tool_name=context.tool_name,
            arguments=context.arguments,
            request_id=context.request_id,
            trace_id=context.trace_id,
            session_key=context.session_key,
            principal=principal_obj,
            auth_context=context.auth_context,
            evidence=context.evidence or [],
        )
        if verification_error is not None:
            return verification_error

        # 5. MCP 工具如果没有显式风险/操作声明，按 UNKNOWN_MCP_TOOL_POLICY 处理。
        mcp_policy_error = self.executor._mcp_policy_denial(
            definition=definition,
            agent_name=context.agent_name,
            tool_name=context.tool_name,
        )
        if mcp_policy_error is not None:
            return mcp_policy_error

        # 6. 写操作、高风险操作或明确审批策略命中时，返回 pending approval，不执行工具。
        if self.approval_guard.requires_approval(definition, context.tool_name):
            return self.approval_guard.build_result(
                agent_name=context.agent_name,
                tool_name=context.tool_name,
                arguments=context.arguments,
                definition=definition,
                principal=principal_obj,
                auth_context=context.auth_context,
                session_key=context.session_key,
                request_id=context.request_id,
                trace_id=context.trace_id,
            )

        # 7. 所有守卫通过后才真正调用本地 callable 或 MCP server。
        return await self.executor._execute_definition(
            definition=definition,
            agent_name=context.agent_name,
            tool_name=context.tool_name,
            arguments=context.arguments,
            principal=principal_obj,
            auth_context=context.auth_context,
        )
