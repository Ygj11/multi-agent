from __future__ import annotations

"""运行时上下文 schema。"""

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.enums.execution import ExecutionMode


class OrchestratorContext(BaseModel):
    """主 Agent 协调用的轻量父上下文。

    这里保存的是路由和子 Agent 构建上下文所需的稳定输入，不承载完整候选列表、
    调试 trace 或工具循环大对象。`entity_bag` 是内部 canonical 实体状态；
    `entities` 是由它投影出的兼容视图，供 Agent/Skill 打分和 prompt 使用。
    """

    original_query: str
    rewritten_query: str
    intent: str
    sub_intent: str | None = None
    entities: dict[str, Any] = Field(default_factory=dict)
    entity_bag: dict[str, Any] = Field(default_factory=dict)
    session_key: str
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    short_summary: str | None = None
    lightweight_knowledge_hints: list[str] = Field(default_factory=list)
    auth_context: dict[str, Any] | None = None


class SubAgentContext(BaseModel):
    """子 Agent 执行任务时使用的任务级上下文。

    该对象在 Skill 选择完成后生成：它包含已选 Skill 的内容、允许工具集合、
    缺实体澄清状态和知识提示。它不是主 Graph state 的替代品，也不负责再次路由 Agent。
    """

    task: dict[str, Any]
    rewritten_query: str
    intent: str
    allowed_tools: list[str] = Field(default_factory=list)
    skill_content: str
    selected_skill_id: str | None = None
    selected_skill_metadata: dict[str, Any] | None = None
    skill_selection_score: float | None = None
    skill_selection_reason: str | None = None
    skill_selection_fallback: bool = False
    skill_selection_source: str | None = None
    execution_mode: ExecutionMode = ExecutionMode.INITIAL
    repair_plan: dict[str, Any] | None = None
    previous_answer: str | None = None
    previous_evidence: list[dict[str, Any]] = Field(default_factory=list)
    previous_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    repair_round: int = 0
    do_not_repeat: list[str] = Field(default_factory=list)
    no_skill_policy: str | None = None
    no_skill_blocked: bool = False
    missing_required_entities: list[str] = Field(default_factory=list)
    need_clarification: bool = False
    clarification_question: str | None = None
    knowledge_hint: str | None = None
    auth_context: dict[str, Any] | None = None
