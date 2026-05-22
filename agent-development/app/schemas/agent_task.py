from __future__ import annotations

"""Task assembly schemas for dispatching work to a selected sub agent."""

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.agent_card import AgentCard


class AgentTaskEnvelope(BaseModel):
    """The full task package created by the main agent for a sub agent."""

    task_id: str
    agent_name: str
    query: str
    original_query: str
    intent: str
    entities: dict[str, Any] = Field(default_factory=dict)
    session_key: str
    request_id: str | None = None
    trace_id: str | None = None
    agent_card: AgentCard
    short_summary: str | None = None
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    lightweight_knowledge_hints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
