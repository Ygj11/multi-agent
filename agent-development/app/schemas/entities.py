from __future__ import annotations

"""Dynamic entity containers shared by query understanding and routing."""

from typing import Any, Literal

from pydantic import BaseModel, Field


EntitySource = Literal["current_query", "recent_turn", "summary", "llm", "rule", "tool_result"]


class EntityMention(BaseModel):
    """One extracted entity mention from a query, summary, turn, LLM, or tool result."""

    type: str
    value: str
    normalized_value: str | None = None
    confidence: float = 1.0
    source: EntitySource | str
    turn_id: str | None = None
    sensitive: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def effective_value(self) -> str:
        """Return normalized value when present, otherwise the raw value."""
        return self.normalized_value or self.value


class EntityBag(BaseModel):
    """Dynamic entity map keyed by entity type.

    Entity types such as policy_no, request_id, claim_no, hospital_name, or
    document_type are dynamic keys inside `entities`; they are not fixed fields
    on ConversationWindow.
    """

    entities: dict[str, list[EntityMention]] = Field(default_factory=dict)

    def add(self, entity: EntityMention) -> None:
        """Append one entity mention."""
        if not entity.type:
            return
        self.entities.setdefault(entity.type, []).append(entity)

    def merge(self, other: "EntityBag") -> "EntityBag":
        """Merge another bag into this bag and return self."""
        for mentions in other.entities.values():
            for mention in mentions:
                self.add(mention)
        return self

    def get_best(self, entity_type: str) -> EntityMention | None:
        """Return the highest-confidence mention for one entity type."""
        mentions = self.entities.get(entity_type) or []
        if not mentions:
            return None
        return sorted(mentions, key=lambda item: item.confidence, reverse=True)[0]

    def get_values(self, entity_type: str) -> list[str]:
        """Return distinct effective values preserving first-seen order."""
        values: list[str] = []
        seen: set[str] = set()
        for mention in self.entities.get(entity_type) or []:
            value = mention.effective_value
            if value not in seen:
                seen.add(value)
                values.append(value)
        return values

    def to_compact_dict(self) -> dict[str, Any]:
        """Return a compact dynamic dict for state, AgentCard scoring, and prompts."""
        compact: dict[str, Any] = {}
        for entity_type in sorted(self.entities):
            values = self.get_values(entity_type)
            if not values:
                continue
            compact[entity_type] = values[0] if len(values) == 1 else values
        return compact

    def has_unique_high_confidence(self, entity_type: str, threshold: float = 0.8) -> bool:
        """True when exactly one distinct value exists and its best confidence is high enough."""
        values = self.get_values(entity_type)
        best = self.get_best(entity_type)
        return len(values) == 1 and best is not None and best.confidence >= threshold

    @classmethod
    def from_compact_dict(
        cls,
        values: dict[str, Any] | None,
        *,
        source: EntitySource | str = "rule",
        confidence: float = 1.0,
    ) -> "EntityBag":
        """Build a bag from a compact dynamic entity dict."""
        bag = cls()
        for entity_type, raw_value in (values or {}).items():
            raw_values = raw_value if isinstance(raw_value, list) else [raw_value]
            for value in raw_values:
                if value is None or value == "":
                    continue
                bag.add(
                    EntityMention(
                        type=str(entity_type),
                        value=str(value),
                        normalized_value=str(value),
                        confidence=confidence,
                        source=source,
                    )
                )
        return bag


class ConversationWindow(BaseModel):
    """Current conversation memory view for query understanding."""

    session_key: str
    summary: str | None = None
    recent_turns: list[dict[str, Any]] = Field(default_factory=list)
    active_task: dict[str, Any] | None = None
    entity_bag: EntityBag = Field(default_factory=EntityBag)
