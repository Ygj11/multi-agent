from __future__ import annotations

"""问题理解与路由共享的动态实体容器。"""

from typing import Any, Literal

from pydantic import BaseModel, Field


EntitySource = Literal["current_query", "recent_turn", "summary", "llm", "rule", "tool_result"]


class EntityMention(BaseModel):
    """一次实体提及，保留来源、置信度和 metadata，供 Resolver 做覆盖判断。"""

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
    """按实体类型分组的 canonical 动态实体集合。

    `policy_no`、`request_id` 等类型是动态 key，不强行固定成巨大 schema。
    Graph 内部以 EntityBag 为事实源；compact dict 只是兼容视图。
    """

    """
    数据m模型
    EntityBag(
        entities={
            "policy_no": [
                EntityMention(
                    type="policy_no",
                    value="P001",
                    confidence=0.95,
                    source="current_query",
                ),
                EntityMention(
                    type="policy_no",
                    value="P002",
                    confidence=0.80,
                    source="history",
                ),
            ],
            "request_id": [
                EntityMention(
                    type="request_id",
                    value="R1001",
                    confidence=0.90,
                    source="current_query",
                )
            ],
        }
    )
    """

    entities: dict[str, list[EntityMention]] = Field(default_factory=dict)

    def add(self, entity: EntityMention) -> None:
        """Add one entity mention, deduplicated by type and effective value."""
        if not entity.type:
            return
        mentions = self.entities.setdefault(entity.type, [])
        for index, existing in enumerate(mentions):
            if existing.effective_value != entity.effective_value:
                continue
            if entity.confidence > existing.confidence:
                mentions[index] = entity
            return
        mentions.append(entity)

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
        """生成 compact entities，供 state 兼容、AgentCard 打分和 prompt 使用。"""
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
    """Query Rewrite / Intent 阶段使用的会话窗口。

    它是问题理解视图，不是全局 memory 对象；后续子 Agent 只接收经过改写和
    实体解析后的上下文，避免在每个阶段重复做历史继承判断。
    """

    session_key: str
    summary: str | None = None
    recent_turns: list[dict[str, Any]] = Field(default_factory=list)
    active_task: dict[str, Any] | None = None
    entity_bag: EntityBag = Field(default_factory=EntityBag)
