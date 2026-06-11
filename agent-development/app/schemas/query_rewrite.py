from __future__ import annotations

"""QueryRewriteNode 的输入语义输出。"""

from typing import Any

from pydantic import BaseModel, Field


class QueryRewriteResult(BaseModel):
    """Query rewrite output with dynamic entities and clarification state."""

    original_query: str
    rewritten_query: str
    is_follow_up: bool = False
    rewrite_type: str = "direct"
    entities: dict[str, Any] = Field(default_factory=dict)
    inherited_entities: dict[str, Any] = Field(default_factory=dict)
    missing_required_entities: list[str] = Field(default_factory=list)
    need_clarification: bool = False
    clarification_question: str | None = None
    confidence: float = 1.0
    reason: str = ""
    entity_bag: dict[str, Any] = Field(default_factory=dict)
    conversation_window: dict[str, Any] = Field(default_factory=dict)
