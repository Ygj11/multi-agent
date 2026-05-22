from __future__ import annotations

"""MCP client errors normalized for ToolExecutor."""


class MCPError(Exception):
    """Base MCP integration error."""


class MCPServerUnavailableError(MCPError):
    """Raised when a registered MCP server is unavailable."""


class MCPToolTimeoutError(MCPError):
    """Raised when an MCP tool call times out."""


class MCPToolError(MCPError):
    """Raised when an MCP tool call fails."""

