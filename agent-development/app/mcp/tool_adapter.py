from __future__ import annotations

"""Adapters between upstream MCP tool schemas and local capabilities."""

from typing import Any

from app.mcp.schemas import MCPServerConfig, MCPToolCapability


def registered_tool_name(config: MCPServerConfig, original_tool_name: str) -> str:
    """Namespace an MCP tool so it cannot collide with local tools."""
    prefix = config.tool_name_prefix or f"mcp.{config.server_name}"
    if original_tool_name.startswith(f"{prefix}."):
        return original_tool_name
    return f"{prefix}.{original_tool_name}"


def capability_from_raw_tool(config: MCPServerConfig, raw_tool: dict[str, Any]) -> MCPToolCapability:
    """Convert an MCP list_tools item to an MCPToolCapability."""
    original_name = str(raw_tool.get("name") or raw_tool.get("tool_name") or "")
    return MCPToolCapability(
        server_name=config.server_name,
        original_tool_name=original_name,
        registered_tool_name=registered_tool_name(config, original_name),
        description=str(raw_tool.get("description") or ""),
        input_schema=raw_tool.get("input_schema") or raw_tool.get("parameters") or {"type": "object", "properties": {}},
        enabled=bool(raw_tool.get("enabled", True)),
        raw_schema=raw_tool,
    )

