from __future__ import annotations

"""Execution pipeline for normal tool calls.

The pipeline keeps the public ToolExecutor API stable while making the guard
order explicit and testable.
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
    """Run normal tool calls through ordered enterprise guards."""

    def __init__(self, executor: ToolExecutor) -> None:
        self.executor = executor
        self.availability_guard = ToolAvailabilityGuard(executor.registry)
        self.argument_guard = ToolArgumentGuard(executor.registry)
        self.authorization_guard = ToolAuthorizationGuard(executor)
        self.verification_guard = ToolVerificationGuard(executor)
        self.approval_guard = ToolApprovalGuard(executor)

    async def run(self, context: ToolExecutionContext) -> ToolResult:
        """Tool existence check and Agent visibility check"""
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

        """LLM 可以提出工具调用，但系统必须先检查它给的参数是否满足工具执行契约；
        不满足就把缺参错误作为 tool observation 返回给 LLM，让 LLM 有机会补参数或向用户澄清。"""
        missing_error = self.argument_guard.check_required(
            agent_name=context.agent_name,
            tool_name=context.tool_name,
            arguments=context.arguments,
        )
        if missing_error is not None:
            return missing_error

        """Pre-tool Authorization Check"""
        principal_obj = self.executor._coerce_principal(context.principal)
        """in fact: use ToolExecutor._authorize"""
        auth_error = await self.authorization_guard.check(
            definition=definition,
            principal=principal_obj,
            arguments=context.arguments,
            action=str(getattr(definition, "operation", "read")),
        )
        if auth_error is not None:
            return auth_error

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

        return await self.executor._execute_definition(
            definition=definition,
            agent_name=context.agent_name,
            tool_name=context.tool_name,
            arguments=context.arguments,
        )
