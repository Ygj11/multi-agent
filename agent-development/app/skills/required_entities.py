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
    """基于 resolved EntityBag 检查 Skill.required_entities。

    这里不做新的正则抽取，也不从任意文本里猜实体。compact entities 为空时，
    只允许从 EntityBag 中唯一高置信值补齐；多值歧义或缺失都转澄清。
    """

    DISPLAY_NAMES = {
        "apply_seq": "保全受理号 apply_seq",
        "policy_no": "保单号 policy_no",
        "endorseType": "保全项 endorseType",
        "request_id": "请求流水号 request_id",
        "error_code": "错误码 error_code",
        "claim_no": "理赔号 claim_no",
    }

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
            display = self._display(ambiguous)
            return RequiredEntityCheckResult(
                entities=merged,
                missing_required_entities=ambiguous,
                need_clarification=True,
                clarification_question=f"上下文里有多个 {display}，请明确要使用哪一个。",
            )
        if missing:
            display = self._display(missing)
            return RequiredEntityCheckResult(
                entities=merged,
                missing_required_entities=missing,
                need_clarification=True,
                clarification_question=f"执行 {skill.name} 还缺少 {display}，请补充后我再继续处理。",
            )
        return RequiredEntityCheckResult(
            entities=merged,
            missing_required_entities=[],
            need_clarification=False,
        )

    @classmethod
    def _display(cls, entity_types: list[str]) -> str:
        return "、".join(cls.DISPLAY_NAMES.get(entity_type, entity_type) for entity_type in entity_types)
