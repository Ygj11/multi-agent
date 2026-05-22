from __future__ import annotations

"""工具调用和工具执行结果 schema。"""

from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """ToolBroker 接收的标准工具调用请求。"""

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
