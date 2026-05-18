from __future__ import annotations

"""运行时上下文 schema。"""

from typing import Any

from pydantic import BaseModel, Field


class OrchestratorContext(BaseModel):
    """主 Agent 协调用的轻量上下文。"""

    original_query: str
    rewritten_query: str
    intent: str
    session_key: str
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    short_summary: str | None = None
    available_subagents: list[str] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
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
    mock_knowledge_hint: str | None = None
    recent_troubleshooting_context: list[dict[str, Any]] = Field(default_factory=list)
