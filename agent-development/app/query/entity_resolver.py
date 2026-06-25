from __future__ import annotations

"""查询理解阶段的 canonical 实体解析服务。

`entity_bag` 是内部唯一事实源，保留来源、置信度、turn_id、敏感标记和
继承/纠正等 metadata。`entities` 只是 `entity_bag.to_compact_dict()` 生成的
兼容投影，供 Agent/Skill 打分、prompt 和 API 兼容使用，不能作为另一份状态
独立维护。
"""

from dataclasses import dataclass, field
from typing import Any

from app.query.entity_extractor import EntityTypeRegistry, default_entity_type_registry
from app.schemas.entities import EntityBag, EntityMention


@dataclass(frozen=True)
class EntityConflict:
    """某一实体类型下无法静默选择的冲突候选。"""

    entity_type: str
    values: list[str]
    source: str
    priority: int


@dataclass(frozen=True)
class EntityResolutionResult:
    """解析后的 canonical EntityBag，以及可能需要澄清的冲突信息。"""

    entity_bag: EntityBag
    conflicts: list[EntityConflict] = field(default_factory=list)
    need_clarification: bool = False
    clarification_question: str | None = None


class EntityResolver:
    """实体解析与规范化。

    Resolver 集中维护实体 alias、值校验、覆盖优先级和冲突策略。调用方不能
    使用 `{**old_entities, **new_entities}` 自行覆盖实体，否则会绕过当前轮优先、
    LLM 低置信过滤、历史唯一继承和多候选澄清这些安全约束。
    """

    # 别名归一化 (Alias Normalization)
    _ALIASES = {
        "policyno": "policy_no",
        "policy_no": "policy_no",
        "applyseq": "apply_seq",
        "apply_seq": "apply_seq",
        "requestid": "request_id",
        "request_id": "request_id",
        "errorcode": "error_code",
        "error_code": "error_code",
        "claimno": "claim_no",
        "claim_no": "claim_no",
        "customerno": "customer_no",
        "customer_no": "customer_no",
        "productcode": "product_code",
        "product_code": "product_code",
        "plancode": "plan_code",
        "plan_code": "plan_code",
        "endorsetype": "endorseType",
        "endorse_type": "endorseType",
        "paymode": "payMode",
        "operatorid": "operatorId",
        "operator_id": "operatorId",
        "applydate": "applyDate",
        "apply_date": "applyDate",
        "surdate": "surDate",
        "sur_date": "surDate",
        "acceptdate": "acceptDate",
        "accept_date": "acceptDate",
        "phonenumber": "phone_number",
        "phone_number": "phone_number",
        "mobile": "phone_number",
        "mobileno": "phone_number",
        "mobile_no": "phone_number",
        "idcard": "id_card",
        "id_card": "id_card",
        "idno": "id_card",
        "id_no": "id_card",
    }

    # 来源优先级管理 (Source Priority)
    _SOURCE_PRIORITY = {
        "current_query": 100,
        "rule": 90,
        "llm": 70,
        "recent_turn": 60,
        "summary": 40,
        "tool_result": 30,
    }

    # LLM 实体只是候选，低于该置信度不进入 canonical entity_bag。
    _LLM_MIN_CONFIDENCE = 0.6

    def __init__(self, entity_type_registry: EntityTypeRegistry | None = None) -> None:
        """使用实体 YAML 注册表校验候选值，避免格式规则在代码中重复维护。"""
        self.entity_type_registry = entity_type_registry or default_entity_type_registry()

    def resolve(
        self,
        *,
        base_bag: EntityBag,
        candidate_bag: EntityBag,
        stage: str,
        parallel_current_entity_types: set[str] | None = None,
    ) -> EntityResolutionResult:
        """
        1. 别名归一化：policyNo -> policy_no，applySeq -> apply_seq
        2. 规范化值：REQ、错误码、产品/险种编码、身份证等转大写
        3. 丢弃否定值、低置信 LLM 值、value_regex 不合法的值
        4. 按实体类型分组；同类型同值去重
        5. 按来源优先级选择，或保留当前轮明确的多值集合
        6. 无法安全选择时返回 conflicts 与 clarification_question



        情况	Resolver 行为	                                                                                是否澄清
        同类型同值多处出现	去重，保留优先级/置信度更高的一条	                                                         否
        当前用户明确输入多个同类值	保留为有序集合，metadata 标记 collection_semantics=explicit_current_values	         否
        历史或其他候选同优先级出现多个不同值	生成 EntityConflict	                                                     是

        “不是 A，是 B”属于更正，不属于多值集合：否定的 A 被丢弃，correction=true 的 B 被保留。
        """
        normalized = EntityBag()
        # 1. 分别规范化 base_bag 和 candidate_bag
        self._extend(normalized, self.normalize_bag(base_bag, stage=stage))
        self._extend(normalized, self.normalize_bag(candidate_bag, stage=stage))

        # 同一当前轮中明确给出的多个值表示用户请求的对象集合，不是历史引用歧义。
        parallel_types = {
            self.canonical_type(entity_type)
            for entity_type in (parallel_current_entity_types or set())
        }
        resolved, conflicts = self._select_by_type(normalized, parallel_current_entity_types=parallel_types)
        clarification_question = self._clarification_question(conflicts)
        return EntityResolutionResult(
            entity_bag=resolved,
            conflicts=conflicts,
            need_clarification=bool(conflicts),
            clarification_question=clarification_question,
        )

    def normalize_bag(self, bag: EntityBag, *, stage: str) -> EntityBag:
        """统一 alias、规范化值，并丢弃低质量候选。"""
        normalized = EntityBag()
        for mentions in bag.entities.values():
            for mention in mentions:
                canonical = self.canonical_type(mention.type)
                candidate = mention.model_copy(
                    update={
                        "type": canonical,
                        "normalized_value": self._normalize_value(canonical, mention.effective_value),
                        "metadata": {
                            **mention.metadata,
                            "canonical_type": canonical,
                            "resolver_stage": stage,
                        },
                    }
                )
                if self._is_acceptable(candidate):
                    normalized.entities.setdefault(candidate.type, []).append(candidate)
        return normalized

    @classmethod
    def canonical_type(cls, entity_type: str) -> str:
        """Return the canonical internal key for a dynamic entity type."""
        raw = str(entity_type).strip()
        key = raw.replace("-", "_")
        normalized_key = key.lower()
        compact_key = normalized_key.replace("_", "")
        return cls._ALIASES.get(normalized_key) or cls._ALIASES.get(compact_key) or raw

    @classmethod
    def compact_from_bag(cls, bag: EntityBag) -> dict[str, Any]:
        """从 canonical entity_bag 生成兼容 compact entities。"""
        resolver = cls()
        return resolver.normalize_bag(bag, stage="compact_projection").to_compact_dict()

    # 冲突检测与解决 (Conflict Resolution)
    def _select_by_type(
        self,
        bag: EntityBag,
        *,
        parallel_current_entity_types: set[str],
    ) -> tuple[EntityBag, list[EntityConflict]]:
        """按实体类型去重、择优，并区分当前轮集合与未决冲突。
        两种情况：
        1、冲突：同一类型有多个不同值，需要用户澄清

        2、当前轮多值集合：用户在同一轮中明确提供了多个值（如多个保单号），这些值应该全部保留
        """
        resolved = EntityBag()
        conflicts: list[EntityConflict] = []
        for entity_type in sorted(bag.entities):
            mentions = bag.entities.get(entity_type) or []
            if not mentions:
                continue
            grouped = self._best_mentions_by_value(mentions)
            ranked = sorted(
                grouped.values(),
                key=lambda mention: (
                    self._priority(mention),
                    mention.confidence,
                    int(mention.metadata.get("span_start", -1) or -1),
                ),
                reverse=True,
            )
            if not ranked:
                continue
            top_priority = self._priority(ranked[0])
            top_candidates = [mention for mention in ranked if self._priority(mention) == top_priority]
            correction_candidates = [mention for mention in top_candidates if mention.metadata.get("correction")]
            if correction_candidates:
                # 用户修正的值优先
                top_candidates = correction_candidates
            top_values = self._distinct_values(top_candidates)
            if len(top_values) > 1:
                if self._is_explicit_current_collection(
                    entity_type=entity_type,
                    mentions=top_candidates,
                    parallel_current_entity_types=parallel_current_entity_types,
                ):
                    # 集合顺序应与用户在当前文本中的出现顺序一致，而不是优先级排序顺序。
                    for mention in sorted(
                        top_candidates,
                        key=lambda item: int(item.metadata.get("span_start", -1) or -1),
                    ):
                        resolved.add(
                            mention.model_copy(
                                update={
                                    "metadata": {
                                        **mention.metadata,
                                        "collection_semantics": "explicit_current_values",
                                    }
                                }
                            )
                        )
                    continue
                conflicts.append(
                    EntityConflict(
                        entity_type=entity_type,
                        values=top_values,
                        source=str(ranked[0].source),
                        priority=top_priority,
                    )
                )
                for mention in top_candidates:
                    resolved.add(mention)
                continue
            resolved.add(ranked[0])
        return resolved, conflicts

    @staticmethod
    def _is_explicit_current_collection(
        *,
        entity_type: str,
        mentions: list[EntityMention],
        parallel_current_entity_types: set[str],
    ) -> bool:
        """仅允许当前轮明确输入的同类多值作为并行对象集合保留。"""
        return (
            entity_type in parallel_current_entity_types
            and bool(mentions)
            and all(mention.source == "current_query" for mention in mentions)
        )

    def _best_mentions_by_value(self, mentions: list[EntityMention]) -> dict[str, EntityMention]:
        # 同值去重，只保留优先级/置信度更高的那条
        grouped: dict[str, EntityMention] = {}
        for mention in mentions:
            value = mention.effective_value
            existing = grouped.get(value)
            if existing is None or (self._priority(mention), mention.confidence) > (self._priority(existing), existing.confidence):
                grouped[value] = mention
        return grouped

    @staticmethod
    def _extend(target: EntityBag, source: EntityBag) -> None:
        for mentions in source.entities.values():
            for mention in mentions:
                target.entities.setdefault(mention.type, []).append(mention)

    @classmethod
    def _priority(cls, mention: EntityMention) -> int:
        if mention.metadata.get("inherited") and mention.source == "recent_turn":
            return 55
        return cls._SOURCE_PRIORITY.get(str(mention.source), 10)

    @staticmethod
    def _distinct_values(mentions: list[EntityMention]) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for mention in mentions:
            value = mention.effective_value
            if value in seen:
                continue
            seen.add(value)
            values.append(value)
        return values

    def _is_acceptable(self, mention: EntityMention) -> bool:
        if mention.metadata.get("negated"):
            return False
        if mention.source == "llm" and mention.confidence < self._LLM_MIN_CONFIDENCE:
            return False
        return self.entity_type_registry.accepts(mention.type, mention.effective_value)

    @staticmethod
    def _normalize_value(entity_type: str, value: str) -> str:
        value = str(value).strip()
        if entity_type in {"request_id", "error_code", "product_code", "plan_code", "id_card"}:
            return value.upper()
        return value

    @staticmethod
    def _clarification_question(conflicts: list[EntityConflict]) -> str | None:
        if not conflicts:
            return None
        parts = [f"{conflict.entity_type}={', '.join(conflict.values)}" for conflict in conflicts]
        return f"识别到多个候选实体，请明确要使用哪一个：{'；'.join(parts)}。"


def build_entity_state_updates(entity_bag: EntityBag) -> dict[str, Any]:
    """生成 Graph 实体字段的唯一同步更新入口。

    任何节点只要改变实体，都必须同时写 `entity_bag` 与由其派生的 `entities`。
    这样可以避免 state 中出现两份版本不同的实体状态。
    """
    canonical_bag = EntityResolver().normalize_bag(entity_bag, stage="state_update")
    return {
        "entity_bag": canonical_bag.model_dump(),
        "entities": canonical_bag.to_compact_dict(),
    }
