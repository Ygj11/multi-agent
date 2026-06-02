from __future__ import annotations

"""Tool bootstrap helpers."""

from app.config.settings import Settings
from app.tools.http_tools import HTTPRequestTool, MCPHTTPCallTool
from app.tools.registry import ToolRegistry
from app.tools.shell_exec_tool import ShellExecTool


def register_admin_restricted_tools(registry: ToolRegistry, settings: Settings) -> None:
    """Register operational tools that stay invisible unless a card opts in."""
    registry.register_private(
        agent_name="admin_agent",
        name="shell_exec",
        tool=ShellExecTool(project_root=settings.project_root, enabled=settings.enable_shell_exec),
        description="Run a tightly restricted allowlisted shell command. Disabled by default.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "array", "description": "Allowlisted command argv, for example ['echo', 'hello']."},
                "timeout": {"type": "number", "description": "Maximum command timeout in seconds, capped by the tool."},
            },
            "required": ["command"],
        },
        is_write=False,
    )
    registry.register_private(
        agent_name="admin_agent",
        name="http_request",
        tool=HTTPRequestTool(
            timeout=settings.http_tool_timeout,
            enabled=settings.enable_http_tools,
            allowed_hosts=settings.allowed_http_tool_hosts,
        ),
        description="Run a restricted allowlisted HTTP GET or POST request. Disabled by default.",
        parameters={
            "type": "object",
            "properties": {
                "method": {"type": "string", "description": "HTTP method, GET or POST."},
                "url": {"type": "string", "description": "Target URL. Host must be allowlisted."},
                "params": {"type": "object", "description": "Optional query parameters."},
                "json_body": {"type": "object", "description": "Optional JSON request body."},
                "timeout": {"type": "number", "description": "Optional timeout in seconds, capped by the tool."},
            },
            "required": ["method", "url"],
        },
    )
    registry.register_private(
        agent_name="admin_agent",
        name="mcp_http.call_tool",
        tool=MCPHTTPCallTool(
            timeout=settings.http_tool_timeout,
            enabled=settings.enable_http_tools,
            allowed_hosts=settings.allowed_http_tool_hosts,
        ),
        description="Call an MCP HTTP gateway through the restricted HTTP request tool. Disabled by default.",
        parameters={
            "type": "object",
            "properties": {
                "base_url": {"type": "string", "description": "MCP HTTP gateway base URL. Host must be allowlisted."},
                "tool_name": {"type": "string", "description": "MCP tool name to call."},
                "arguments": {"type": "object", "description": "Arguments passed to the MCP tool."},
                "endpoint_path": {"type": "string", "description": "Gateway endpoint path, default /mcp/tools/call."},
                "timeout": {"type": "number", "description": "Optional timeout in seconds, capped by the tool."},
            },
            "required": ["base_url", "tool_name"],
        },
    )
