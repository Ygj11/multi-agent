from __future__ import annotations

"""LLM semantic reranking for skill metadata candidates."""

from dataclasses import dataclass
from typing import Any

from app.llm.base import LLMProvider
from app.llm.output_schemas import SkillSelectionLLMOutput, parse_llm_json_schema
from app.prompts.loader import PromptLoader, default_prompt_loader
from app.runtime.decision_trace import LLMAttempt
from app.runtime.failure_codes import (
    LLM_DISABLED,
    LLM_JSON_PARSE_FAILED,
    LLM_PROVIDER_ERROR,
    LLM_SCHEMA_VALIDATION_FAILED,
    LLM_STATUS_DISABLED,
    LLM_STATUS_INVALID_OUTPUT,
    LLM_STATUS_PARSE_FAILED,
    LLM_STATUS_PROVIDER_ERROR,
    LLM_STATUS_SUCCESS,
    SKILL_RERANK_UNUSABLE,
)
from app.schemas.skill import SkillMetadata, SkillSelectionContext
from app.skills.scorer import ScoredSkill


@dataclass(frozen=True)
class SkillRerankResult:
    """A valid LLM rerank decision constrained to the provided candidates."""

    selected_skill: SkillMetadata
    score: float
    reason: str
    llm_confidence: float
    llm_reason: str


class SkillLLMReranker:
    """Reranks Top-K skill metadata without exposing full skill bodies."""

    def __init__(
        self,
        *,
        llm_provider: LLMProvider | None,
        enabled: bool = True,
        top_k: int = 3,
        min_margin: float = 3.0,
        min_confident_score: float = 7.0,
        min_llm_confidence: float = 0.45,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.enabled = enabled
        self.top_k = top_k
        self.min_margin = min_margin
        self.min_confident_score = min_confident_score
        self.min_llm_confidence = min_llm_confidence
        self.prompt_loader = prompt_loader or default_prompt_loader
        self.last_attempt = LLMAttempt(llm_status=LLM_STATUS_DISABLED, fallback_reason=LLM_DISABLED)

    def should_rerank(self, context: SkillSelectionContext, scored: list[ScoredSkill]) -> bool:
        if not self.enabled or self.llm_provider is None or len(scored) <= 1:
            if self.llm_provider is None:
                self.last_attempt = LLMAttempt(llm_status=LLM_STATUS_DISABLED, fallback_reason=LLM_DISABLED)
            return False
        top_score = scored[0].score
        second_score = scored[1].score
        query = f"{context.original_query} {context.rewritten_query}"
        semantic_signal = any(
            token in query
            for token in (
                "但是",
                "但",
                "却",
                "没有",
                "未",
                "完成",
                "结束",
                "成功",
                "after",
                "apply_",
            )
        )
        return (
            top_score < self.min_confident_score
            or top_score - second_score < self.min_margin
            or semantic_signal
            or len(query) >= 30
        )

    async def rerank(
        self,
        *,
        agent_name: str,
        context: SkillSelectionContext,
        scored: list[ScoredSkill],
    ) -> SkillRerankResult | None:
        prompt_trace = self.prompt_loader.scene_trace("skill_selection")
        if self.llm_provider is None:
            self.last_attempt = LLMAttempt(
                llm_status=LLM_STATUS_DISABLED,
                fallback_reason=LLM_DISABLED,
                extra=prompt_trace,
            )
            return None
        top_scored = scored[: self.top_k]
        candidates = [item.skill for item in top_scored]
        candidate_ids = {candidate.skill_id for candidate in candidates}
        summaries = [self.metadata_summary(item.skill, item.score, item.reason) for item in top_scored]
        try:
            response = await self.llm_provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": self.prompt_loader.render_scene_system("skill_selection"),
                    },
                    {
                        "role": "user",
                        "content": self.prompt_loader.render_scene_user(
                            "skill_selection",
                            agent_name=agent_name,
                            original_query=context.original_query,
                            rewritten_query=context.rewritten_query,
                            intent=context.intent,
                            sub_intent=context.sub_intent,
                            entities=context.entities,
                            candidates=summaries,
                        ),
                    },
                ],
                tools=None,
                scene="skill_selection",
                request_id=context.request_id,
                trace_id=context.trace_id,
                session_key=context.session_key,
            )
        except Exception as exc:
            self.last_attempt = LLMAttempt(
                llm_status=LLM_STATUS_PROVIDER_ERROR,
                fallback_reason=LLM_PROVIDER_ERROR,
                detail=str(exc),
                extra=prompt_trace,
            )
            return None
        if response.finish_reason == "error" or response.error:
            self.last_attempt = LLMAttempt(
                llm_status=LLM_STATUS_PROVIDER_ERROR,
                fallback_reason=LLM_PROVIDER_ERROR,
                detail=response.error or "llm_error",
                extra={
                    **prompt_trace,
                    "finish_reason": response.finish_reason,
                    "model": response.model,
                },
            )
            return None
        parsed = parse_llm_json_schema(response.content, SkillSelectionLLMOutput)
        parse_trace = {
            **prompt_trace,
            "finish_reason": response.finish_reason,
            "model": response.model,
            "parse_status": parsed.parse_status,
            "schema_status": "valid" if parsed.success else "invalid",
            "schema_name": parsed.schema_name,
        }
        if not parsed.success:
            self.last_attempt = LLMAttempt(
                llm_status=LLM_STATUS_PARSE_FAILED
                if parsed.error_code == LLM_JSON_PARSE_FAILED
                else LLM_STATUS_INVALID_OUTPUT,
                fallback_reason=LLM_JSON_PARSE_FAILED
                if parsed.error_code == LLM_JSON_PARSE_FAILED
                else LLM_SCHEMA_VALIDATION_FAILED,
                detail=parsed.error_detail,
                extra=parse_trace,
            )
            return None
        output = parsed.data
        if not isinstance(output, SkillSelectionLLMOutput):
            self.last_attempt = LLMAttempt(
                llm_status=LLM_STATUS_INVALID_OUTPUT,
                fallback_reason=LLM_SCHEMA_VALIDATION_FAILED,
                detail="schema result type mismatch",
                extra=parse_trace,
            )
            return None
        selected_skill_id = output.selected_skill_id
        if selected_skill_id not in candidate_ids:
            self.last_attempt = LLMAttempt(
                llm_status=LLM_STATUS_INVALID_OUTPUT,
                fallback_reason=SKILL_RERANK_UNUSABLE,
                detail=f"selected_skill_id={selected_skill_id}",
                extra=parse_trace,
            )
            return None
        confidence = output.confidence
        if confidence < self.min_llm_confidence:
            self.last_attempt = LLMAttempt(
                llm_status=LLM_STATUS_INVALID_OUTPUT,
                fallback_reason=SKILL_RERANK_UNUSABLE,
                detail=f"low_confidence={confidence}",
                extra=parse_trace,
            )
            return None
        selected = next(candidate for candidate in candidates if candidate.skill_id == selected_skill_id)
        rule_score = next(item.score for item in top_scored if item.skill.skill_id == selected_skill_id)
        llm_reason = output.reason
        reason = f"llm semantic rerank selected {selected_skill_id}; {llm_reason}"
        self.last_attempt = LLMAttempt(
            llm_status=LLM_STATUS_SUCCESS,
            extra=parse_trace,
        )
        return SkillRerankResult(
            selected_skill=selected,
            score=max(rule_score, self.min_confident_score),
            reason=reason,
            llm_confidence=confidence,
            llm_reason=llm_reason,
        )

    @staticmethod
    def metadata_summary(skill: SkillMetadata, score: float, reason: str) -> dict[str, Any]:
        return {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "description": skill.description,
            "agent": skill.agent,
            "intent": skill.intent,
            "sub_intents": skill.sub_intents,
            "intent_tags": skill.intent_tags,
            "required_entities": skill.required_entities,
            "optional_entities": skill.optional_entities,
            "required_context": skill.required_context,
            "business_domain": skill.business_domain,
            "routing_keywords": skill.routing_keywords,
            "routing_negative_keywords": skill.routing_negative_keywords,
            "private_tools": skill.private_tools,
            "public_tools": skill.public_tools,
            "mcp_tools": skill.mcp_tools,
            "rule_score": score,
            "rule_reason": reason,
        }
