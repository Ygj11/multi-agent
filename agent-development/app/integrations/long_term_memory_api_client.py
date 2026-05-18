from __future__ import annotations

"""未来长期记忆服务 API client 示例。"""

from typing import Any

from app.integrations.base_http_client import BaseIntegrationHTTPClient


class LongTermMemoryAPIClient:
    """未来用于替换 LongTermMemoryManager stub。"""

    def __init__(self, http_client: BaseIntegrationHTTPClient) -> None:
        self.http = http_client

    async def retrieve(self, query: str, session_key: str, top_k: int = 5, request_id: str | None = None, trace_id: str | None = None) -> list[dict[str, Any]]:
        # TODO: 接 PostgreSQL/Milvus/记忆治理服务，并过滤敏感健康和身份数据。
        data = await self.http.post_json(
            "/memory/retrieve",
            payload={"query": query, "session_key": session_key, "top_k": top_k},
            request_id=request_id,
            trace_id=trace_id,
        )
        return list(data.get("memories", []))

    async def extract_and_update(self, payload: dict[str, Any], request_id: str | None = None, trace_id: str | None = None) -> dict[str, Any]:
        # TODO: 未来写入长期记忆前必须做脱敏、审批、合规策略和审计。
        return await self.http.post_json("/memory/extract-and-update", payload=payload, request_id=request_id, trace_id=trace_id)

