from __future__ import annotations

"""LLM semantic reranking for skill metadata candidates."""

from dataclasses import dataclass
from typing import Any

from app.llm.base import LLMProvider
from app.prompts.loader import PromptLoader, default_prompt_loader
from app.query.json_utils import parse_json_object
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

    def should_rerank(self, context: SkillSelectionContext, scored: list[ScoredSkill]) -> bool:
        if not self.enabled or self.llm_provider is None or len(scored) <= 1:
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
        if self.llm_provider is None:
            return None
        top_scored = scored[: self.top_k]
        candidates = [item.skill for item in top_scored]
        candidate_ids = {candidate.skill_id for candidate in candidates}
        summaries = [self.metadata_summary(item.skill, item.score, item.reason) for item in top_scored]
        response = await self.llm_provider.chat(
            messages=[
                {
                    "role": "system",
                    "content": self.prompt_loader.render("skill_selection/system.md"),
                },
                {
                    "role": "user",
                    "content": self.prompt_loader.render(
                        "skill_selection/user.md",
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
        )
        data = parse_json_object(response.content)
        if data is None:
            return None
        selected_skill_id = str(data.get("selected_skill_id") or "")
        if selected_skill_id not in candidate_ids:
            return None
        try:
            confidence = float(data.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            return None
        if confidence < self.min_llm_confidence:
            return None
        selected = next(candidate for candidate in candidates if candidate.skill_id == selected_skill_id)
        rule_score = next(item.score for item in top_scored if item.skill.skill_id == selected_skill_id)
        llm_reason = str(data.get("reason") or "llm semantic rerank")
        reason = f"llm semantic rerank selected {selected_skill_id}; {llm_reason}"
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
