from __future__ import annotations

"""QueryRewriteNode 的输入语义输出。"""

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.entities import EntityBag
from app.schemas.enums.query import RewriteType


class QueryRewriteResult(BaseModel):
    """Query Rewrite 的输出协议。

    为兼容旧调用保留 `entities` 字段，但它必须由 `entity_bag` 派生。
    调用方不应把 `entities` 当成可独立修改的第二份实体状态。
    """

    original_query: str
    rewritten_query: str
    is_follow_up: bool = False
    rewrite_type: RewriteType = RewriteType.DIRECT
    entities: dict[str, Any] = Field(default_factory=dict)
    inherited_entities: dict[str, Any] = Field(default_factory=dict)
    missing_required_entities: list[str] = Field(default_factory=list)
    need_clarification: bool = False
    clarification_question: str | None = None
    confidence: float = 1.0
    reason: str = ""
    entity_bag: dict[str, Any] = Field(default_factory=dict)
    conversation_window: dict[str, Any] = Field(default_factory=dict)
    llm_status: str | None = None
    fallback_used: bool = False
    fallback_source: str | None = None
    fallback_reason: str | None = None
    decision_trace: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """保证 compact entities 始终是 entity_bag 的派生兼容视图。"""
        if not self.entity_bag:
            return
        self.entities = EntityBag(**self.entity_bag).to_compact_dict()
