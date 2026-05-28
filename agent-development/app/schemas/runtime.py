from __future__ import annotations

"""运行时上下文 schema。"""

from typing import Any

from pydantic import BaseModel, Field


class OrchestratorContext(BaseModel):
    """主 Agent 协调用的轻量上下文。"""

    original_query: str
    rewritten_query: str
    intent: str
    sub_intent: str | None = None
    entities: dict[str, Any] = Field(default_factory=dict)
    entity_bag: dict[str, Any] = Field(default_factory=dict)
    conversation_window: dict[str, Any] = Field(default_factory=dict)
    session_key: str
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    short_summary: str | None = None
    available_subagents: list[str] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    agent_candidate_summaries: list[dict[str, Any]] = Field(default_factory=list)
    lightweight_knowledge_hints: list[str] = Field(default_factory=list)


class SubAgentContext(BaseModel):
    """子 Agent 执行任务时使用的任务级上下文。"""

    task: dict[str, Any]
    rewritten_query: str
    intent: str
    allowed_tools: list[str] = Field(default_factory=list)
    skill_content: str
    selected_skill_id: str | None = None
    selected_skill_metadata: dict[str, Any] | None = None
    skill_selection_score: float | None = None
    skill_selection_reason: str | None = None
    missing_required_entities: list[str] = Field(default_factory=list)
    need_clarification: bool = False
    clarification_question: str | None = None
    knowledge_hint: str | None = None
