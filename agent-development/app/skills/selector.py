from __future__ import annotations

"""Hybrid metadata-only SkillSelector facade."""

from app.llm.base import LLMProvider
from app.observability.logger import log_event, preview_text
from app.runtime.failure_codes import NO_ENABLED_SKILLS
from app.schemas.skill import SkillMetadata, SkillSelectionContext, SkillSelectionResult
from app.skills.reranker import SkillLLMReranker
from app.skills.scorer import SkillRuleScorer
from app.skills.selection_policy import SkillSelectionPolicy


class SkillSelector:
    """在已选 Agent 内选择一个 Skill。

    选择器只读取 SkillMetadata，不读取 Skill 正文。规则分数足够确定时直接使用；
    分数接近或语义复杂时才让 LLM 在候选 metadata 中 rerank。
    """

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
        """从候选 metadata 中选择最合适的 Skill。"""
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
            log_event(
                "skill_not_selected",
                request_id=context.request_id,
                trace_id=context.trace_id,
                session_key=context.session_key,
                node="skill_selector",
                message="No enabled skill candidates",
                data={"agent_name": agent_name},
            )
            return SkillSelectionResult(
                selected_skill_id=None,
                selected_skill_metadata=None,
                score=0.0,
                reason=f"no enabled skills for agent: {agent_name}",
                fallback=True,
                selection_source="none",
                fallback_used=True,
                fallback_source="skill_selection",
                fallback_reason=NO_ENABLED_SKILLS,
                decision_trace={"source": "skill_selection", "method": "none", "fallback_reason": NO_ENABLED_SKILLS},
            )

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
            rerank_attempt=self.reranker.last_attempt if rerank_attempted else None,
        )

        if decision.fallback:
            log_event(
                "skill_not_selected",
                request_id=context.request_id,
                trace_id=context.trace_id,
                session_key=context.session_key,
                node="skill_selector",
                message="No confident skill match",
                data={
                    "agent_name": agent_name,
                    "selected_skill_id": decision.selected.skill_id if decision.selected else None,
                    "score": decision.score,
                    "reason": decision.reason,
                    "fallback_reason": decision.fallback_reason,
                    "llm_status": decision.llm_status,
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
                "selected_skill_id": decision.selected.skill_id if decision.selected else None,
                "score": decision.score,
                "reason": decision.reason,
                "selection_source": decision.selection_source,
                "llm_confidence": decision.llm_confidence,
                "llm_reason": decision.llm_reason,
                "llm_status": decision.llm_status,
                "fallback_used": decision.fallback,
                "fallback_reason": decision.fallback_reason,
                "query_preview": preview_text(context.rewritten_query),
            },
        )
        return SkillSelectionResult(
            selected_skill_id=decision.selected.skill_id if decision.selected else None,
            selected_skill_metadata=decision.selected,
            score=decision.score,
            reason=decision.reason,
            fallback=decision.fallback,
            selection_source=decision.selection_source,
            llm_confidence=decision.llm_confidence,
            llm_reason=decision.llm_reason,
            llm_status=decision.llm_status,
            fallback_used=decision.fallback,
            fallback_source="skill_selection" if decision.fallback else None,
            fallback_reason=decision.fallback_reason,
            decision_trace=decision.decision_trace or {},
        )
