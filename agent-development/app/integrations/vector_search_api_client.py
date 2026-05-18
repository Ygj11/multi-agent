from __future__ import annotations

"""未来向量/关键词检索 API client 示例。"""

from typing import Any

from app.integrations.base_http_client import BaseIntegrationHTTPClient


class VectorSearchAPIClient:
    """未来用于接 Milvus / Elasticsearch / OpenSearch。"""

    def __init__(self, http_client: BaseIntegrationHTTPClient) -> None:
        self.http = http_client

    async def search_vectors(self, query: str, top_k: int, filters: dict[str, Any] | None = None, request_id: str | None = None, trace_id: str | None = None) -> list[dict[str, Any]]:
        # TODO: 接 Milvus/向量服务，补充 embedding、metadata filter、租户隔离和脱敏。
        data = await self.http.post_json(
            "/search/vector",
            payload={"query": query, "top_k": top_k, "filters": filters or {}},
            request_id=request_id,
            trace_id=trace_id,
        )
        return list(data.get("results", []))

    async def keyword_search(self, query: str, top_k: int, filters: dict[str, Any] | None = None, request_id: str | None = None, trace_id: str | None = None) -> list[dict[str, Any]]:
        # TODO: 接 Elasticsearch/OpenSearch/BM25，补充字段映射、版本过滤和权限过滤。
        data = await self.http.post_json(
            "/search/keyword",
            payload={"query": query, "top_k": top_k, "filters": filters or {}},
            request_id=request_id,
            trace_id=trace_id,
        )
        return list(data.get("results", []))

