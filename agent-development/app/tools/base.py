from __future__ import annotations

"""Base tool types for the card-driven tool layer."""

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field


ToolCallable = Callable[..., Awaitable[Any]]
ToolScope = Literal["public", "private", "mcp"]
ToolSource = Literal["local", "mcp"]


class ToolDefinition(BaseModel):
    """Registered tool metadata and callable."""

    name: str
    callable: ToolCallable = Field(exclude=True)
    description: str = ""
    scope: ToolScope = "public"
    source: ToolSource = "local"
    agent_name: str | None = None
    server_name: str | None = None
    original_name: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    is_write: bool = False

    model_config = {"arbitrary_types_allowed": True}
