from __future__ import annotations

"""工具调用和工具执行结果 schema。"""

from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """Normalized tool call request."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    trace_id: str | None = None
    session_key: str | None = None
    agent_name: str | None = None


class ToolResult(BaseModel):
    """Standardized tool execution result."""

    name: str
    allowed: bool = True
    success: bool
    result: Any = None
    error: str | None = None
    agent_name: str | None = None
    duration_ms: int | None = None
    needs_human_approval: bool = False
    approval_payload: dict[str, Any] | None = None
    pending_tool_call: dict[str, Any] | None = None
    approval_id: str | None = None
