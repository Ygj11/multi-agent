from __future__ import annotations

"""未来真实审计服务 API client 示例。"""

from typing import Any

from app.integrations.base_http_client import BaseIntegrationHTTPClient


class AuditAPIClient:
    """未来用于替换本地 SQLite tool audit。"""

    def __init__(self, http_client: BaseIntegrationHTTPClient) -> None:
        self.http = http_client

    async def write_tool_call_log(self, payload: dict[str, Any], request_id: str | None = None, trace_id: str | None = None) -> dict[str, Any]:
        # TODO: 接真实审计平台，补充签名、token、客户信息脱敏和审计分级。
        return await self.http.post_json("/audit/tool-calls", payload=payload, request_id=request_id, trace_id=trace_id)

    async def query_tool_call_logs(self, session_key: str, request_id: str | None = None, trace_id: str | None = None) -> list[dict[str, Any]]:
        # TODO: 未来增加权限校验，避免跨租户读取审计数据。
        data = await self.http.get_json(
            "/audit/tool-calls",
            params={"session_key": session_key},
            request_id=request_id,
            trace_id=trace_id,
        )
        return list(data.get("logs", []))

