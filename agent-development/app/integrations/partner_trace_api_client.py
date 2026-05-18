from __future__ import annotations

"""未来合作方渠道 trace API client 示例。"""

from typing import Any

from app.integrations.base_http_client import BaseIntegrationHTTPClient


class PartnerTraceAPIClient:
    """未来用于替换 partner_trace.get_request_detail fake MCP tool。"""

    def __init__(self, http_client: BaseIntegrationHTTPClient) -> None:
        self.http = http_client

    async def get_request_detail(self, request_id: str, trace_id: str | None = None) -> dict[str, Any]:
        # TODO: 接真实渠道 trace 系统，补充合作方鉴权、字段映射和敏感字段脱敏。
        return await self.http.get_json(
            f"/partner-trace/requests/{request_id}",
            request_id=request_id,
            trace_id=trace_id,
        )

