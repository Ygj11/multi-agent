from __future__ import annotations

"""Base tool types for the card-driven tool layer."""

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field


ToolCallable = Callable[..., Awaitable[Any]]
ToolScope = Literal["public", "private", "mcp"]
ToolSource = Literal["local", "mcp"]
ToolOperation = Literal["read", "write", "notify", "execute", "search"]
DataClassification = Literal["public", "internal", "confidential", "sensitive"]


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
    operation: ToolOperation = "read"
    required_scopes: list[str] = Field(default_factory=list)
    resource_type: str | None = None
    resource_id_arg: str | None = None
    pre_answer_filter_required: bool = True
    data_domains: list[str] = Field(default_factory=list)
    data_classification: DataClassification = "internal"
    risk_level: Literal["low", "medium", "high"] = "low"
    precondition_id: str | None = None
    idempotency_required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}
