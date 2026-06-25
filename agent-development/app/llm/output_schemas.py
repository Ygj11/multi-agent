from __future__ import annotations

"""Strict structured output schemas for LLM decision prompts."""

from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.query.json_utils import parse_json_object


T = TypeVar("T", bound=BaseModel)


class LLMStructuredParseResult(BaseModel):
    """Result of parsing one LLM JSON response into a strict schema."""

    success: bool
    data: BaseModel | None = None
    raw: dict[str, Any] | None = None
    error_code: str | None = None
    error_detail: str | None = None
    parse_status: Literal["success", "json_parse_failed", "schema_validation_failed"] = "success"
    schema_name: str


class _StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryRewriteLLMOutput(_StrictOutput):
    is_follow_up: bool
    rewritten_query: str
    rewrite_type: Literal["direct", "contextual_follow_up", "clarification_reply", "new_request", "clarification_required"]
    entities: dict[str, Any] = Field(
        default_factory=dict,
        description="仅放当前用户消息提供或语义暗示的实体候选，不放历史继承实体。",
    )
    inherited_entities: dict[str, Any] = Field(
        default_factory=dict,
        description="仅放从历史上下文继承的实体候选。",
    )
    missing_required_entities: list[str] = Field(default_factory=list)
    need_clarification: bool
    clarification_question: str | None = None
    confidence: float
    reason: str = "llm_json_rewrite"


class IntentRecognitionLLMOutput(_StrictOutput):
    intent: str
    sub_intent: str | None = None
    confidence: float
    entities: dict[str, Any] = Field(default_factory=dict)
    missing_required_entities: list[str] = Field(default_factory=list)
    need_clarification: bool
    clarification_question: str | None = None
    is_follow_up: bool = False
    reason: str = "llm_json_classification"


class AgentSelectionLLMOutput(_StrictOutput):
    selected_agent: str
    confidence: float
    reason: str = "llm_router"
    need_clarification: bool = False
    clarification_question: str | None = None


class SkillSelectionLLMOutput(_StrictOutput):
    selected_skill_id: str
    confidence: float
    reason: str = "llm semantic rerank"


SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    "QueryRewriteLLMOutput": QueryRewriteLLMOutput,
    "IntentRecognitionLLMOutput": IntentRecognitionLLMOutput,
    "AgentSelectionLLMOutput": AgentSelectionLLMOutput,
    "SkillSelectionLLMOutput": SkillSelectionLLMOutput,
}


def parse_llm_json_schema(text: str | None, schema: type[T]) -> LLMStructuredParseResult:
    """Parse an LLM JSON object and validate it against a strict Pydantic model."""
    raw = parse_json_object(text)
    schema_name = schema.__name__
    if raw is None:
        return LLMStructuredParseResult(
            success=False,
            data=None,
            raw=None,
            error_code="llm_json_parse_failed",
            error_detail="response content is not a JSON object",
            parse_status="json_parse_failed",
            schema_name=schema_name,
        )
    try:
        data = schema.model_validate(raw)
    except ValidationError as exc:
        return LLMStructuredParseResult(
            success=False,
            data=None,
            raw=raw,
            error_code="llm_schema_validation_failed",
            error_detail=str(exc),
            parse_status="schema_validation_failed",
            schema_name=schema_name,
        )
    return LLMStructuredParseResult(
        success=True,
        data=data,
        raw=raw,
        error_code=None,
        error_detail=None,
        parse_status="success",
        schema_name=schema_name,
    )
