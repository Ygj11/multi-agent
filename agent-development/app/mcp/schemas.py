from __future__ import annotations

"""Schemas for MCP client-side integration."""

from typing import Any

from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel):
    """Configuration for one upstream MCP server."""

    server_name: str
    enabled: bool = True
    transport: str
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    timeout: int = 30
    tool_name_prefix: str | None = None


class MCPToolCapability(BaseModel):
    """One tool exposed by an upstream MCP server."""

    server_name: str
    original_tool_name: str
    registered_tool_name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    raw_schema: dict[str, Any] | None = None


class MCPServerStatus(BaseModel):
    """Cached availability state for one MCP server."""

    server_name: str
    available: bool = False
    last_error: str | None = None
    last_refresh_at: str | None = None
    tool_count: int = 0

