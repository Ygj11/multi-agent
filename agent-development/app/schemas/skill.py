from __future__ import annotations

"""Skill metadata、内容和选择结果 schema。"""

from typing import Any

from pydantic import BaseModel, Field


class SkillMetadata(BaseModel):
    """从 SKILL.md YAML frontmatter 中读取的轻量 metadata。"""

    skill_id: str
    name: str
    description: str
    agent: str
    intent_tags: list[str] = Field(default_factory=list)
    business_domain: list[str] = Field(default_factory=list)
    required_context: list[str] = Field(default_factory=list)
    enabled: bool = True
    is_default: bool = False
    source_path: str


class SkillContent(BaseModel):
    """选中 skill 后才加载的完整 SKILL.md 内容。"""

    metadata: SkillMetadata
    content: str


class SkillSelectionContext(BaseModel):
    """SkillSelector 使用的最小必要上下文。"""

    agent_name: str
    intent: str
    original_query: str
    rewritten_query: str
    session_key: str
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
