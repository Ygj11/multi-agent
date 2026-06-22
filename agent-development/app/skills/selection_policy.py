from __future__ import annotations

"""Final decision policy for skill selection."""

from dataclasses import dataclass

from app.schemas.skill import SkillMetadata
from app.runtime.decision_trace import LLMAttempt
from app.runtime.failure_codes import (
    LLM_STATUS_SUCCESS,
    NO_CONFIDENT_SKILL,
    NO_ENABLED_SKILLS,
    SKILL_RERANK_UNUSABLE,
)
from app.skills.reranker import SkillRerankResult
from app.skills.scorer import ScoredSkill


@dataclass(frozen=True)
class SkillDecision:
    selected: SkillMetadata | None
    score: float
    reason: str
    fallback: bool
    selection_source: str
    llm_confidence: float | None = None
    llm_reason: str | None = None
    llm_status: str | None = None
    fallback_reason: str | None = None
    decision_trace: dict | None = None


class SkillSelectionPolicy:
    """Applies fallback and source rules after scoring and optional rerank."""

    def __init__(self, *, min_confident_score: float = 7.0) -> None:
        self.min_confident_score = min_confident_score

    def decide(
        self,
        *,
        candidates: list[SkillMetadata],
        scored: list[ScoredSkill],
        rerank_result: SkillRerankResult | None,
        rerank_attempted: bool,
        rerank_attempt: LLMAttempt | None = None,
    ) -> SkillDecision:
        if not scored:
            return SkillDecision(
                selected=None,
                score=0.0,
                reason="no enabled skill candidates",
                fallback=True,
                selection_source="none",
                fallback_reason=NO_ENABLED_SKILLS,
                decision_trace={"source": "skill_selection", "method": "none", "fallback_reason": NO_ENABLED_SKILLS},
            )

        top = scored[0]
        selected = top.skill
        score = top.score
        reason = top.reason
        selection_source = "rule"
        llm_confidence = None
        llm_reason = None
        llm_status = None
        fallback_reason = None
        decision_trace: dict | None = {"source": "skill_selection", "method": "rule"}

        if rerank_attempted:
            if rerank_result is not None:
                selected = rerank_result.selected_skill
                score = rerank_result.score
                reason = rerank_result.reason
                selection_source = "llm_rerank"
                llm_confidence = rerank_result.llm_confidence
                llm_reason = rerank_result.llm_reason
                llm_status = LLM_STATUS_SUCCESS
                decision_trace = {
                    "source": "skill_selection",
                    "method": "llm_rerank",
                    "llm_status": LLM_STATUS_SUCCESS,
                    **(rerank_attempt.trace(source="skill_selection") if rerank_attempt else {}),
                }
            else:
                selection_source = "fallback"
                llm_status = rerank_attempt.llm_status if rerank_attempt else None
                fallback_reason = (rerank_attempt.fallback_reason if rerank_attempt else None) or SKILL_RERANK_UNUSABLE
                reason = f"llm rerank unavailable; fallback to rule top1: {reason}"
                decision_trace = {
                    "source": "skill_selection",
                    "method": "rule_after_llm_rerank_failed",
                    **(rerank_attempt.trace(source="skill_selection") if rerank_attempt else {}),
                }

        if score < self.min_confident_score:
            return SkillDecision(
                selected=None,
                score=0.0,
                reason="no confident skill match",
                fallback=True,
                selection_source="none",
                llm_confidence=llm_confidence,
                llm_reason=llm_reason,
                llm_status=llm_status,
                fallback_reason=fallback_reason or NO_CONFIDENT_SKILL,
                decision_trace={
                    "source": "skill_selection",
                    "method": selection_source,
                    "fallback_reason": fallback_reason or NO_CONFIDENT_SKILL,
                    **(decision_trace or {}),
                },
            )

        return SkillDecision(
            selected=selected,
            score=score,
            reason=reason,
            fallback=False,
            selection_source=selection_source,
            llm_confidence=llm_confidence,
            llm_reason=llm_reason,
            llm_status=llm_status,
            fallback_reason=fallback_reason,
            decision_trace=decision_trace,
        )
