from __future__ import annotations

"""Stable tool execution error codes."""


TOOL_NOT_FOUND = "tool_not_found"
TOOL_NOT_AVAILABLE_FOR_AGENT = "tool_not_available_for_agent"
MISSING_REQUIRED_ARGUMENT = "missing_required_argument"
PERMISSION_DENIED = "permission_denied"
VERIFICATION_FAILED = "verification_failed"
HUMAN_APPROVAL_REQUIRED = "human_approval_required"
TOOL_TIMEOUT = "tool_timeout"
TOOL_EXECUTION_EXCEPTION = "tool_execution_exception"
TOOL_RESULT_SCHEMA_INVALID = "tool_result_schema_invalid"
MCP_SERVER_UNAVAILABLE = "mcp_server_unavailable"
MCP_TOOL_TIMEOUT = "mcp_tool_timeout"
MCP_TOOL_ERROR = "mcp_tool_error"
MCP_TOOL_POLICY_DENIED = "mcp_tool_policy_denied"
