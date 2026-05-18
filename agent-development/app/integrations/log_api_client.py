from __future__ import annotations

"""未来真实日志平台 API client 示例。"""

from typing import Any

from app.integrations.base_http_client import BaseIntegrationHTTPClient


class LogAPIClient:
    """未来用于替换 query_internal_log mock tool。"""

    def __init__(self, http_client: BaseIntegrationHTTPClient) -> None:
        self.http = http_client

    async def query_internal_log(self, request_id: str, trace_id: str | None = None) -> dict[str, Any]:
        # TODO: 接真实网关日志/链路日志平台，映射 interface_name、error_code、sign 信息，并做签名脱敏。
        return await self.http.get_json(
            f"/logs/requests/{request_id}",
            request_id=request_id,
            trace_id=trace_id,
        )

