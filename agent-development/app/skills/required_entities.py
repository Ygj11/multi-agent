from __future__ import annotations

"""Required entity checks for selected skills."""

from dataclasses import dataclass
from typing import Any

from app.schemas.entities import EntityBag
from app.schemas.skill import SkillMetadata


@dataclass(frozen=True)
class RequiredEntityCheckResult:
    """Result of checking selected skill entity requirements."""

    entities: dict[str, Any]
    missing_required_entities: list[str]
    need_clarification: bool
    clarification_question: str | None = None


class RequiredEntityChecker:
    """Check Skill.required_entities against dynamic EntityBag."""

    def check(
        self,
        *,
        skill: SkillMetadata,
        entities: dict[str, Any],
        entity_bag: EntityBag,
    ) -> RequiredEntityCheckResult:
        merged = dict(entities)
        missing: list[str] = []
        ambiguous: list[str] = []

        for entity_type in skill.required_entities:
            value = merged.get(entity_type)
            if value not in (None, "", []):
                continue
            if entity_bag.has_unique_high_confidence(entity_type):
                best = entity_bag.get_best(entity_type)
                if best is not None:
                    merged[entity_type] = best.effective_value
                    continue
            values = entity_bag.get_values(entity_type)
            if len(values) > 1:
                ambiguous.append(entity_type)
            else:
                missing.append(entity_type)

        if ambiguous:
            return RequiredEntityCheckResult(
                entities=merged,
                missing_required_entities=ambiguous,
                need_clarification=True,
                clarification_question=f"上下文里有多个 {ambiguous[0]}，请明确要使用哪一个。",
            )
        if missing:
            return RequiredEntityCheckResult(
                entities=merged,
                missing_required_entities=missing,
                need_clarification=True,
                clarification_question=f"执行 {skill.name} 还缺少 {', '.join(missing)}，请补充后我再继续。",
            )
        return RequiredEntityCheckResult(
            entities=merged,
            missing_required_entities=[],
            need_clarification=False,
        )
