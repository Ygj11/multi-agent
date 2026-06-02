from __future__ import annotations

"""Pre-tool verification guard wrapper."""


class ToolVerificationGuard:
    """Run pre-tool verification through ToolExecutor services."""

    def __init__(self, executor) -> None:
        self.executor = executor

    async def check(
        self,
        *,
        agent_name: str,
        tool_name: str,
        arguments: dict,
        request_id: str | None,
        trace_id: str | None,
        session_key: str | None,
        principal,
        auth_context: dict | None,
        evidence: list[dict],
        approval_id: str | None = None,
    ):
        return await self.executor._verify_pre_tool(
            agent_name=agent_name,
            tool_name=tool_name,
            arguments=arguments,
            request_id=request_id,
            trace_id=trace_id,
            session_key=session_key,
            principal=principal,
            auth_context=auth_context,
            evidence=evidence,
            approval_id=approval_id,
        )
