from __future__ import annotations

"""Schemas shared by LLM providers."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    """LLM response normalized across internal and OpenSDK providers."""

    content: str | None
    tool_calls: list[Any] = field(default_factory=list)
    has_tool_calls: bool = False
    reasoning_content: str | None = None
    finish_reason: str = "stop"
    raw_response: dict[str, Any] | None = None
    error: str | None = None
    model: str | None = None
    request_id: str | None = None
    latency_ms: int | None = None

