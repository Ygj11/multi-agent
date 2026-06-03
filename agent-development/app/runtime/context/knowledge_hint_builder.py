from __future__ import annotations

"""Knowledge hint construction for orchestrator and sub-agent contexts."""

from app.knowledge.service import KnowledgeService
from app.observability.logger import log_event


class KnowledgeHintBuilder:
    """Builds lightweight RAG hints without owning broader context assembly."""

    def __init__(self, knowledge_service: KnowledgeService | None = None) -> None:
        self.knowledge_service = knowledge_service

    async def build_lightweight_hints(self, *, query: str, intent: str) -> list[str]:
        if self.knowledge_service is None:
            return []
        chunks = await self.knowledge_service.pre_search(query=query, intent=intent, top_k=3)
        log_event(
            "knowledge_hint_loaded",
            node="context_builder",
            message="Lightweight knowledge hints loaded",
            data={"knowledge_hint_count": len(chunks), "sources": [chunk.source for chunk in chunks]},
        )
        return [chunk.content for chunk in chunks]

    async def build_subagent_knowledge_hint(self, *, query: str, namespaces: list[str] | None = None) -> str | None:
        if self.knowledge_service is None:
            return None
        chunks = await self.knowledge_service.search(query=query, top_k=3, namespaces=namespaces or None)
        log_event(
            "subagent_context_built",
            node="context_builder",
            message="Subagent knowledge context built",
            data={"knowledge_hint_count": len(chunks), "sources": [chunk.source for chunk in chunks]},
        )
        if not chunks:
            return None
        return "\n".join(chunk.content for chunk in chunks)
