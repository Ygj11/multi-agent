from __future__ import annotations

from app.knowledge.schemas import KnowledgeChunk


class FakeKnowledgeService:
    """Test-only KnowledgeService fake."""

    def __init__(self, chunks: list[KnowledgeChunk] | None = None) -> None:
        self.chunks = chunks or [
            KnowledgeChunk(
                content="fake knowledge result",
                source="test_fake",
                score=1.0,
                metadata={"keywords": ["test"]},
            )
        ]

    async def search(self, query: str, top_k: int = 3) -> list[KnowledgeChunk]:
        return self.chunks[:top_k]

    async def pre_search(self, query: str, intent: str, top_k: int = 3) -> list[KnowledgeChunk]:
        return await self.search(query, top_k)
