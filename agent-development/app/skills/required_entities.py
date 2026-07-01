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

    Query Rewrite 阶段已经负责实体抽取、上下文继承和冲突处理；这里不再做新的
    正则抽取，也不从任意文本里猜实体，只负责在选中 Skill 后做最后一道必填实体门禁。

    典型场景：
    1. 当前轮缺失、EntityBag 中有唯一高置信历史值：
       例如用户上一轮给过保单号，本轮只补充“001028”，compact entities 里暂时没有
       policy_no 时，可以从 EntityBag 唯一值补齐。
    2. 当前轮缺失、EntityBag 中有多个候选：
       例如上下文里同时出现两个历史保单号，但本轮没有明确指代哪一个，这里转澄清，
       避免后续 Skill 或工具误用实体。
    3. 当前轮明确多值：
       例如“查询保单 A 和保单 B”，Query Rewrite 会把它保留为集合；当前实现只要
       compact entities 中存在非空 list，就认为 required_entities 已满足。是否允许多值
       应继续由 Skill 语义和 Tool 参数 schema 判断，后续可增加 cardinality 配置细化。
    4. 状态投影异常：
       正常情况下 entities 应由 entity_bag.to_compact_dict() 派生；如果调用方传入的
       compact entities 为空但 EntityBag 仍有值，这里只允许唯一高置信值补齐，多值转澄清。
    """

    # 用于把内部实体 key 转成面向用户的澄清文案。比如缺少 policy_no 时，
    # 不直接问“请补充 policy_no”，而是问“请补充保单号 policy_no”。
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
