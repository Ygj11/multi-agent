from __future__ import annotations

"""Authorization guard wrapper."""


class ToolAuthorizationGuard:
    """Run scope/resource authorization through ToolExecutor services."""

    def __init__(self, executor) -> None:
        self.executor = executor

    async def check(self, *, definition, principal, arguments: dict, action: str, approval_id: str | None = None):
        return await self.executor._authorize(
            definition=definition,
            principal=principal,
            arguments=arguments,
            action=action,
            approval_id=approval_id,
        )
