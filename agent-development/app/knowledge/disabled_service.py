from __future__ import annotations

"""Disabled KnowledgeService implementation."""

from app.knowledge.schemas import KnowledgeChunk
from app.observability.logger import log_event


class DisabledKnowledgeService:
    """Safe empty KnowledgeService used when external knowledge API is disabled."""

    disabled_reason = "knowledge api disabled"

    async def search(self, query: str, top_k: int = 3, namespaces: list[str] | None = None) -> list[KnowledgeChunk]:
        log_event(
            "knowledge_api_disabled",
            node="knowledge_service",
            message="Knowledge API is disabled; search returns no chunks",
            data={"query": query, "top_k": top_k, "namespaces": namespaces or []},
        )
        return []

    async def pre_search(self, query: str, intent: str, top_k: int = 3, namespaces: list[str] | None = None) -> list[KnowledgeChunk]:
        log_event(
            "knowledge_api_disabled",
            node="knowledge_service",
            message="Knowledge API is disabled; pre_search returns no chunks",
            data={"query": query, "intent": intent, "top_k": top_k, "namespaces": namespaces or []},
        )
        return []
