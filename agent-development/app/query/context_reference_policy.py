from __future__ import annotations

"""Policy-backed context reference rules for query rewrite."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.schemas.entities import EntityBag


DEFAULT_CONTEXT_REFERENCE_POLICY_PATH = Path(__file__).with_name("context_reference_policy.yaml")


@dataclass(frozen=True)
class QueryContextReferencePolicy:
    """Declarative policy for deciding whether a query references conversation history."""

    version: str
    explicit_reference_signals: tuple[str, ...] = ()
    weak_follow_up_signals: tuple[str, ...] = ()
    strong_anchor_entity_types: frozenset[str] = frozenset()
    entity_type_aliases: dict[str, str] = field(default_factory=dict)
    ordinal_targets: dict[str, int] = field(default_factory=dict)
    short_query_without_anchor_max_len: int = 16
    policy_name: str = "query_context_reference_policy"

    @classmethod
    def load(cls, path: Path | str = DEFAULT_CONTEXT_REFERENCE_POLICY_PATH) -> "QueryContextReferencePolicy":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("context reference policy root must be a mapping")
        return cls(
            version=str(raw.get("version") or "unknown"),
            explicit_reference_signals=tuple(str(item) for item in raw.get("explicit_reference_signals") or []),
            weak_follow_up_signals=tuple(str(item) for item in raw.get("weak_follow_up_signals") or []),
            strong_anchor_entity_types=frozenset(str(item) for item in raw.get("strong_anchor_entity_types") or []),
            entity_type_aliases={str(key): str(value) for key, value in (raw.get("entity_type_aliases") or {}).items()},
            ordinal_targets={str(key): int(value) for key, value in (raw.get("ordinal_targets") or {}).items()},
            short_query_without_anchor_max_len=int(raw.get("short_query_without_anchor_max_len") or 16),
        )

    def trace(self) -> dict[str, str]:
        return {"policy_name": self.policy_name, "policy_version": self.version}

    def ordinal_target(self, query: str) -> tuple[int | None, str | None]:
        for hint, index in self.ordinal_targets.items():
            if hint in query:
                return index, hint
        return None, None

    def has_explicit_reference(self, text: str) -> bool:
        return self._has_any(text, self.explicit_reference_signals)

    def has_weak_follow_up(self, text: str) -> bool:
        return self._has_any(text, self.weak_follow_up_signals)

    def has_strong_anchor(self, bag: EntityBag) -> bool:
        return bool(self.strong_anchor_entity_types.intersection(bag.entities))

    def is_short_query_without_anchor(self, text: str, bag: EntityBag) -> bool:
        return not self.has_strong_anchor(bag) and not bag.to_compact_dict() and len(text.strip()) <= self.short_query_without_anchor_max_len

    def remaining_required_entities(self, raw_required: Any, bag: EntityBag) -> list[str]:
        required = [str(item) for item in raw_required or [] if item]
        compact = bag.to_compact_dict()
        present = set(compact)
        present.update(alias for alias, canonical in self.entity_type_aliases.items() if canonical in present)
        return [item for item in required if item not in present and self.entity_type_aliases.get(item, item) not in present]

    @staticmethod
    def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
        lower = text.lower()
        return any(keyword.lower() in lower for keyword in keywords)
