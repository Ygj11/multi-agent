from __future__ import annotations

"""Hybrid metadata-only SkillSelector facade."""

from app.llm.base import LLMProvider
from app.observability.logger import log_event, preview_text
from app.schemas.skill import SkillMetadata, SkillSelectionContext, SkillSelectionResult
from app.skills.reranker import SkillLLMReranker
from app.skills.scorer import SkillRuleScorer
from app.skills.selection_policy import SkillSelectionPolicy


class SkillSelector:
    """Select one skill from metadata without reading skill bodies."""

    min_confident_score = 7.0
    min_llm_confidence = 0.45

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        enable_llm_rerank: bool = True,
        top_k: int = 3,
        min_margin: float = 3.0,
        scorer: SkillRuleScorer | None = None,
        reranker: SkillLLMReranker | None = None,
        selection_policy: SkillSelectionPolicy | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.enable_llm_rerank = enable_llm_rerank
        self.top_k = top_k
        self.min_margin = min_margin
        self.scorer = scorer or SkillRuleScorer()
        self.reranker = reranker or SkillLLMReranker(
            llm_provider=llm_provider,
            enabled=enable_llm_rerank,
            top_k=top_k,
            min_margin=min_margin,
            min_confident_score=self.min_confident_score,
            min_llm_confidence=self.min_llm_confidence,
        )
        self.selection_policy = selection_policy or SkillSelectionPolicy(
            min_confident_score=self.min_confident_score,
        )

    async def select(
        self,
        *,
        agent_name: str,
        context: SkillSelectionContext,
        candidates: list[SkillMetadata],
    ) -> SkillSelectionResult:
        """Select the best skill from candidate metadata."""
        log_event(
            "skill_selection_started",
            request_id=context.request_id,
            trace_id=context.trace_id,
            session_key=context.session_key,
            node="skill_selector",
            message="Skill selection started",
            data={"agent_name": agent_name, "candidate_count": len(candidates)},
        )
        if not candidates:
            raise ValueError(f"no enabled skills for agent: {agent_name}")

        scored = [self.scorer.score(context, candidate) for candidate in candidates]
        scored.sort(key=lambda item: item.score, reverse=True)

        rerank_attempted = self.reranker.should_rerank(context, scored)
        rerank_result = None
        if rerank_attempted:
            rerank_result = await self.reranker.rerank(
                agent_name=agent_name,
                context=context,
                scored=scored,
            )

        decision = self.selection_policy.decide(
            candidates=candidates,
            scored=scored,
            rerank_result=rerank_result,
            rerank_attempted=rerank_attempted,
        )

        if decision.fallback:
            log_event(
                "skill_selection_fallback",
                request_id=context.request_id,
                trace_id=context.trace_id,
                session_key=context.session_key,
                node="skill_selector",
                message="Skill selection fallback",
                data={
                    "agent_name": agent_name,
                    "selected_skill_id": decision.selected.skill_id,
                    "score": decision.score,
                    "reason": decision.reason,
                },
            )

        log_event(
            "skill_selected",
            request_id=context.request_id,
            trace_id=context.trace_id,
            session_key=context.session_key,
            node="skill_selector",
            message="Skill selected",
            data={
                "agent_name": agent_name,
                "selected_skill_id": decision.selected.skill_id,
                "score": decision.score,
                "reason": decision.reason,
                "selection_source": decision.selection_source,
                "llm_confidence": decision.llm_confidence,
                "llm_reason": decision.llm_reason,
                "query_preview": preview_text(context.rewritten_query),
            },
        )
        return SkillSelectionResult(
            selected_skill_id=decision.selected.skill_id,
            selected_skill_metadata=decision.selected,
            score=decision.score,
            reason=decision.reason,
            fallback=decision.fallback,
            selection_source=decision.selection_source,
            llm_confidence=decision.llm_confidence,
            llm_reason=decision.llm_reason,
        )
