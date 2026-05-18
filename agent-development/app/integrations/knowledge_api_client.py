from __future__ import annotations

"""未来真实知识服务 API client 示例。"""

from typing import Any

from app.integrations.base_http_client import BaseIntegrationHTTPClient


class KnowledgeAPIClient:
    """未来用于替换 InMemoryKnowledgeService。"""

    def __init__(self, http_client: BaseIntegrationHTTPClient) -> None:
        self.http = http_client

    async def search(self, query: str, top_k: int = 3, request_id: str | None = None, trace_id: str | None = None) -> list[dict[str, Any]]:
        # TODO: 替换真实知识检索地址、鉴权、租户/产品/版本过滤字段映射。
        data = await self.http.post_json(
            "/knowledge/search",
            payload={"query": query, "top_k": top_k},
            request_id=request_id,
            trace_id=trace_id,
        )
        return list(data.get("chunks", []))

    async def pre_search(self, query: str, intent: str, top_k: int = 3, request_id: str | None = None, trace_id: str | None = None) -> list[dict[str, Any]]:
        # TODO: 未来可接轻量知识预检索 endpoint，并补充字段脱敏策略。
        data = await self.http.post_json(
            "/knowledge/pre-search",
            payload={"query": query, "intent": intent, "top_k": top_k},
            request_id=request_id,
            trace_id=trace_id,
        )
        return list(data.get("chunks", []))

