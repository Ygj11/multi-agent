from __future__ import annotations

"""Final decision policy for skill selection."""

from dataclasses import dataclass

from app.schemas.skill import SkillMetadata
from app.skills.reranker import SkillRerankResult
from app.skills.scorer import ScoredSkill


@dataclass(frozen=True)
class SkillDecision:
    selected: SkillMetadata
    score: float
    reason: str
    fallback: bool
    selection_source: str
    llm_confidence: float | None = None
    llm_reason: str | None = None


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
    ) -> SkillDecision:
        top = scored[0]
        selected = top.skill
        score = top.score
        reason = top.reason
        selection_source = "rule"
        llm_confidence = None
        llm_reason = None

        if rerank_attempted:
            if rerank_result is not None:
                selected = rerank_result.selected_skill
                score = rerank_result.score
                reason = rerank_result.reason
                selection_source = "llm_rerank"
                llm_confidence = rerank_result.llm_confidence
                llm_reason = rerank_result.llm_reason
            else:
                selection_source = "fallback"
                reason = f"llm rerank unavailable; fallback to rule top1: {reason}"

        if score < self.min_confident_score:
            default = self.default_skill(candidates)
            return SkillDecision(
                selected=default,
                score=0.0,
                reason=f"no confident match; fallback to default skill {default.skill_id}",
                fallback=True,
                selection_source="fallback",
                llm_confidence=llm_confidence,
                llm_reason=llm_reason,
            )

        return SkillDecision(
            selected=selected,
            score=score,
            reason=reason,
            fallback=False,
            selection_source=selection_source,
            llm_confidence=llm_confidence,
            llm_reason=llm_reason,
        )

    @staticmethod
    def default_skill(candidates: list[SkillMetadata]) -> SkillMetadata:
        for candidate in candidates:
            if candidate.is_default:
                return candidate
        return candidates[0]
