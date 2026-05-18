from __future__ import annotations

"""子 Agent 任务和结果 schema。"""

from typing import Any

from pydantic import BaseModel, Field


class SubAgentTask(BaseModel):
    """主 Agent 分配给子 Agent 的结构化任务。"""

    name: str
    query: str
    intent: str
    session_key: str
    original_query: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubAgentResult(BaseModel):
    """子 Agent 返回给主 Agent 的结构化结果。"""

    name: str
    answer: str
    diagnosis: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    recommendation: str | None = None
    responsibility: str | None = None
    confidence: float = 0.8
    selected_skill_id: str | None = None
    selected_skill_metadata: dict[str, Any] | None = None
    skill_selection_score: float | None = None
    skill_selection_reason: str | None = None
