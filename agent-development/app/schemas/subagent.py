from __future__ import annotations

"""子 Agent 任务和结果 schema。"""

from typing import Any

from pydantic import BaseModel, Field


class SubAgentTask(BaseModel):
    """主 Agent 分配给子 Agent 的结构化任务。

    任务只携带 selected agent 的引用、查询、意图、实体和身份上下文；
    完整 AgentCard、Skill 内容和工具 schema 由子 Agent 运行时重新加载。
    """

    agent_name: str
    agent_card_version: str
    query: str
    intent: str
    session_key: str
    original_query: str
    request_id: str | None = None
    trace_id: str | None = None
    auth_context: dict[str, Any] | None = None
    entities: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubAgentResult(BaseModel):
    """子 Agent 返回给主 Graph 的结构化结果。"""

    name: str | None = None
    agent_name: str | None = None
    task_id: str | None = None
    answer: str
    diagnosis: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    recommendation: str | None = None
    responsibility: str | None = None
    confidence: float = 0.8
    needs_human_approval: bool = False
    approval_payloads: list[dict[str, Any]] = Field(default_factory=list)
    risk_level: str = "low"
    metadata: dict[str, Any] = Field(default_factory=dict)
    selected_skill_id: str | None = None
    selected_skill_metadata: dict[str, Any] | None = None
    skill_selection_score: float | None = None
    skill_selection_reason: str | None = None

    def model_post_init(self, __context: Any) -> None:
        """Keep the old `name` field and new `agent_name` field in sync."""
        if self.agent_name is None and self.name is not None:
            self.agent_name = self.name
        if self.name is None and self.agent_name is not None:
            self.name = self.agent_name
