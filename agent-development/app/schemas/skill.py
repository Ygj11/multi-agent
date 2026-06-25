from __future__ import annotations

"""Skill metadata、内容和选择结果 schema。"""

from typing import Any

from pydantic import BaseModel, Field, model_validator


class SkillMetadata(BaseModel):
    """从 SKILL.md YAML frontmatter 中读取的轻量 metadata。"""

    skill_id: str
    name: str
    description: str
    agent: str
    intent: str | None = None
    # 可选的路由细化条件：空列表不增加 sub_intent 约束。
    sub_intents: list[str] = Field(default_factory=list)
    intent_tags: list[str]
    # 必填 frontmatter 字段。``[]`` 明确表示该 Skill 没有实体前置条件；
    # 配置的实体会在选中后校验。
    required_entities: list[str]
    # 仅作为可选选择信号；空列表不提供可选实体信号。
    optional_entities: list[str] = Field(default_factory=list)
    # 必填 frontmatter 字段。配置的名称会与 AgentCard 校验；``[]`` 明确表示
    # 此 Skill 不预期使用私有工具。
    private_tools: list[str]
    public_tools: list[str] = Field(default_factory=list)
    # 必填布尔值：不允许根据缺失字段猜测该安全策略。
    requires_tool_evidence: bool
    enabled: bool
    business_domain: list[str] = Field(default_factory=list)
    # 仅作为可选路由信号；空列表不提供上下文信号。
    required_context: list[str] = Field(default_factory=list)
    routing_keywords: list[str] = Field(default_factory=list)
    routing_negative_keywords: list[str] = Field(default_factory=list)
    source_path: str

    @model_validator(mode="after")
    def validate_enterprise_metadata(self) -> "SkillMetadata":
        """Reject legacy simplified skill metadata."""
        if "." not in self.skill_id:
            raise ValueError("skill_id must use '<agent_name>.<skill_name>' format")
        if not self.skill_id.startswith(f"{self.agent}."):
            raise ValueError("skill_id must start with '<agent>.'")
        if not self.name.strip():
            raise ValueError("name is required")
        if not self.description.strip():
            raise ValueError("description is required")
        if not self.intent_tags:
            raise ValueError("intent_tags must contain at least one item")
        return self


class SkillContent(BaseModel):
    """选中 Skill 后才加载的完整 SKILL.md 内容。

    Skill 内容是业务 SOP，会进入子 Agent prompt；未入选的 Skill 只暴露
    metadata 给选择器，避免把所有 SOP 一次性塞给 LLM。
    """

    metadata: SkillMetadata
    content: str


class SkillSelectionContext(BaseModel):
    """SkillSelector 使用的最小必要上下文。

    这里来自 OrchestratorContext + SubAgentTask，是“在已选 Agent 内选择 Skill”
    的上下文，不承担 Agent 路由职责。
    """

    agent_name: str
    intent: str
    sub_intent: str | None = None
    original_query: str
    rewritten_query: str
    session_key: str
    entities: dict[str, Any] = Field(default_factory=dict)
    entity_bag: dict[str, Any] = Field(default_factory=dict)
    short_summary: str | None = None
    recent_messages_summary: str | None = None
    lightweight_knowledge_hints: list[str] = Field(default_factory=list)
    request_id: str | None = None
    trace_id: str | None = None
    extracted_error_code: str | None = None
    extracted_request_id: str | None = None
    business_domain: list[str] = Field(default_factory=lambda: ["health_insurance_onboarding"])
    extra: dict[str, Any] = Field(default_factory=dict)


class SkillSelectionResult(BaseModel):
    """SkillSelector 的选择结果。"""

    selected_skill_id: str | None = None
    selected_skill_metadata: SkillMetadata | None = None
    score: float
    reason: str
    fallback: bool = False
    selection_source: str = "rule"
    llm_confidence: float | None = None
    llm_reason: str | None = None
    missing_required_entities: list[str] = Field(default_factory=list)
    need_clarification: bool = False
    clarification_question: str | None = None
    llm_status: str | None = None
    fallback_used: bool = False
    fallback_source: str | None = None
    fallback_reason: str | None = None
    decision_trace: dict[str, Any] = Field(default_factory=dict)
