from __future__ import annotations

"""External KnowledgeService API client."""

from typing import Any

from app.integrations.base_http_client import BaseIntegrationHTTPClient
from app.knowledge.chunk_post_processor import KnowledgeChunkPostProcessor
from app.knowledge.schemas import KnowledgeChunk
from app.observability.logger import log_event


class KnowledgeAPIClient:
    """KnowledgeService implementation backed by an external API."""

    def __init__(
        self,
        http_client: BaseIntegrationHTTPClient,
        post_processor: KnowledgeChunkPostProcessor | None = None,
    ) -> None:
        self.http = http_client
        self.post_processor = post_processor or KnowledgeChunkPostProcessor()

    async def search(
        self,
        query: str,
        top_k: int = 3,
        namespaces: list[str] | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> list[KnowledgeChunk]:
        return await self._search(
            path="/knowledge/search",
            payload={"query": query, "top_k": top_k, "namespaces": namespaces or []},
            query=query,
            top_k=top_k,
            request_id=request_id,
            trace_id=trace_id,
            event_name="knowledge_search",
        )

    async def pre_search(
        self,
        query: str,
        intent: str,
        top_k: int = 3,
        namespaces: list[str] | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> list[KnowledgeChunk]:
        return await self._search(
            path="/knowledge/pre-search",
            payload={"query": query, "intent": intent, "top_k": top_k, "namespaces": namespaces or []},
            query=query,
            top_k=top_k,
            request_id=request_id,
            trace_id=trace_id,
            event_name="knowledge_pre_search",
        )

    async def _search(
        self,
        *,
        path: str,
        payload: dict[str, Any],
        query: str,
        top_k: int,
        request_id: str | None,
        trace_id: str | None,
        event_name: str,
    ) -> list[KnowledgeChunk]:
        log_event(
            f"{event_name}_started",
            request_id=request_id,
            trace_id=trace_id,
            node="knowledge_api_client",
            message="Knowledge API search started",
            data={"query": query, "top_k": top_k, "path": path},
        )
        try:
            data = await self.http.post_json(path, payload=payload, request_id=request_id, trace_id=trace_id)
            raw_chunks = self._extract_raw_chunks(data)
            chunks = self.post_processor.normalize_many(raw_chunks, top_k=top_k)
            log_event(
                f"{event_name}_finished",
                request_id=request_id,
                trace_id=trace_id,
                node="knowledge_api_client",
                message="Knowledge API search finished",
                data={"hit_count": len(chunks), "raw_count": len(raw_chunks), "sources": [item.source for item in chunks]},
            )
            return chunks
        except Exception as exc:
            log_event(
                f"{event_name}_failed",
                level="WARNING",
                request_id=request_id,
                trace_id=trace_id,
                node="knowledge_api_client",
                message="Knowledge API search failed",
                data={"error": str(exc), "query": query, "top_k": top_k},
            )
            return []

    @staticmethod
    def _extract_raw_chunks(data: dict[str, Any]) -> list[Any]:
        for key in ("chunks", "results", "documents"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        nested = data.get("data")
        if isinstance(nested, dict):
            for key in ("chunks", "results", "documents"):
                value = nested.get(key)
                if isinstance(value, list):
                    return value
        return []
