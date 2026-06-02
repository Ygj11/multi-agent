from __future__ import annotations

"""Tool existence and AgentCard visibility guards."""

from app.schemas.tool import ToolResult


class ToolAvailabilityGuard:
    """Validate that a tool exists and is visible to the calling agent."""

    def __init__(self, registry) -> None:
        self.registry = registry

    def check_exists(self, *, agent_name: str, tool_name: str):
        definition = self.registry.get_definition(tool_name)
        if definition is not None:
            return definition, None
        return None, ToolResult(
            name=tool_name,
            agent_name=agent_name,
            allowed=False,
            success=False,
            error="tool_not_found",
        )

    def check_visible(self, *, agent_name: str, tool_name: str, agent_card) -> ToolResult | None:
        if self.registry.is_tool_available_for_agent(agent_name, tool_name, agent_card):
            return None
        return ToolResult(
            name=tool_name,
            agent_name=agent_name,
            allowed=False,
            success=False,
            error="tool_not_available_for_agent",
        )
