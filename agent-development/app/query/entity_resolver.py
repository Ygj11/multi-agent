from __future__ import annotations

"""Canonical entity resolution for query understanding.

entity_bag is the canonical internal entity state.
entities is only a derived compatibility view built from entity_bag.to_compact_dict().
"""

import re
from dataclasses import dataclass, field
from typing import Any

from app.schemas.entities import EntityBag, EntityMention


@dataclass(frozen=True)
class EntityConflict:
    """One unresolved conflict for an entity type."""

    entity_type: str
    values: list[str]
    source: str
    priority: int


@dataclass(frozen=True)
class EntityResolutionResult:
    """Resolved canonical bag plus clarification metadata."""

    entity_bag: EntityBag
    conflicts: list[EntityConflict] = field(default_factory=list)
    need_clarification: bool = False
    clarification_question: str | None = None


class EntityResolver:
    """Resolve aliases, merge mentions, and apply one entity overwrite policy."""

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
    _SOURCE_PRIORITY = {
        "current_query": 100,
        "rule": 90,
        "llm": 70,
        "recent_turn": 60,
        "summary": 40,
        "tool_result": 30,
    }
    _LLM_MIN_CONFIDENCE = 0.75
    _FORMAT_PATTERNS = {
        "policy_no": re.compile(r"^920\d{13}$", re.IGNORECASE),
        "apply_seq": re.compile(r"^930\d{12}$", re.IGNORECASE),
        "endorseType": re.compile(r"^00\d{4}$", re.IGNORECASE),
        "request_id": re.compile(r"^REQ(?:[_-]?[0-9][A-Za-z0-9_-]*|[_-][A-Za-z0-9_-]+)$", re.IGNORECASE),
        "error_code": re.compile(r"^(?:E|ERR[_-]?|ERROR[_-]?)\d{3,6}$", re.IGNORECASE),
        "claim_no": re.compile(r"^(?:CLM|CLAIM)[_-]?[A-Za-z0-9_-]+$", re.IGNORECASE),
        "product_code": re.compile(r"^PM[A-Za-z0-9_-]{1,30}$", re.IGNORECASE),
        "plan_code": re.compile(r"^H[A-Za-z0-9_-]{1,30}$", re.IGNORECASE),
        "phone_number": re.compile(r"^1[3-9]\d{9}$"),
        "id_card": re.compile(
            r"^[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9X]$",
            re.IGNORECASE,
        ),
    }

    def resolve(
        self,
        *,
        base_bag: EntityBag,
        candidate_bag: EntityBag,
        stage: str,
    ) -> EntityResolutionResult:
        """Merge two bags and return the resolved canonical entity state."""
        normalized = EntityBag()
        self._extend(normalized, self.normalize_bag(base_bag, stage=stage))
        self._extend(normalized, self.normalize_bag(candidate_bag, stage=stage))
        resolved, conflicts = self._select_by_type(normalized)
        clarification_question = self._clarification_question(conflicts)
        return EntityResolutionResult(
            entity_bag=resolved,
            conflicts=conflicts,
            need_clarification=bool(conflicts),
            clarification_question=clarification_question,
        )

    def normalize_bag(self, bag: EntityBag, *, stage: str) -> EntityBag:
        """Normalize entity aliases and drop invalid low-quality candidates."""
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
        """Build the compact compatibility view from canonical entity_bag."""
        resolver = cls()
        return resolver.normalize_bag(bag, stage="compact_projection").to_compact_dict()

    def _select_by_type(self, bag: EntityBag) -> tuple[EntityBag, list[EntityConflict]]:
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
                top_candidates = correction_candidates
            top_values = self._distinct_values(top_candidates)
            if len(top_values) > 1:
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

    def _best_mentions_by_value(self, mentions: list[EntityMention]) -> dict[str, EntityMention]:
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
        pattern = self._FORMAT_PATTERNS.get(mention.type)
        if pattern is None:
            return bool(mention.effective_value)
        return bool(pattern.fullmatch(mention.effective_value))

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
    """Return synchronized graph updates for canonical entity_bag and compact entities."""
    canonical_bag = EntityResolver().normalize_bag(entity_bag, stage="state_update")
    return {
        "entity_bag": canonical_bag.model_dump(),
        "entities": canonical_bag.to_compact_dict(),
    }
