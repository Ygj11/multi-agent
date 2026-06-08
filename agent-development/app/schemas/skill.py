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
    sub_intents: list[str] = Field(default_factory=list)
    intent_tags: list[str]
    required_entities: list[str]
    optional_entities: list[str] = Field(default_factory=list)
    private_tools: list[str]
    public_tools: list[str] = Field(default_factory=list)
    mcp_tools: list[str] = Field(default_factory=list)
    enabled: bool
    is_default: bool
    business_domain: list[str] = Field(default_factory=list)
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
    """选中 skill 后才加载的完整 SKILL.md 内容。"""

    metadata: SkillMetadata
    content: str


class SkillSelectionContext(BaseModel):
    """SkillSelector 使用的最小必要上下文。"""

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
    extracted_interface_name: str | None = None
    business_domain: list[str] = Field(default_factory=lambda: ["health_insurance_onboarding"])
    extra: dict[str, Any] = Field(default_factory=dict)


class SkillSelectionResult(BaseModel):
    """SkillSelector 的选择结果。"""

    selected_skill_id: str
    selected_skill_metadata: SkillMetadata
    score: float
    reason: str
    fallback: bool = False
    selection_source: str = "rule"
    llm_confidence: float | None = None
    llm_reason: str | None = None
    missing_required_entities: list[str] = Field(default_factory=list)
    need_clarification: bool = False
    clarification_question: str | None = None
