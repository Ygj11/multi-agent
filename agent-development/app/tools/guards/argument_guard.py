from __future__ import annotations

"""Tool argument validation guard."""

from app.schemas.tool import ToolResult


class ToolArgumentGuard:
    """Validate required arguments from ToolDefinition parameters."""

    def __init__(self, registry) -> None:
        self.registry = registry

    def check_required(self, *, agent_name: str, tool_name: str, arguments: dict) -> ToolResult | None:
        required = self.registry.get_required_arguments(tool_name)
        missing = [name for name in required if name not in arguments or arguments.get(name) is None]
        if not missing:
            return None
        return ToolResult(
            name=tool_name,
            agent_name=agent_name,
            allowed=True,
            success=False,
            error=f"missing_required_argument:{','.join(missing)}",
            missing_required_arguments=missing,
        )
