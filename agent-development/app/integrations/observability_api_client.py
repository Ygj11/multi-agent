from __future__ import annotations

"""未来可观测平台 API client 示例。"""

from typing import Any

from app.integrations.base_http_client import BaseIntegrationHTTPClient


class ObservabilityAPIClient:
    """未来用于替换/扩展 Runtime Execution Logging 或接入 OpenTelemetry 网关。"""

    def __init__(self, http_client: BaseIntegrationHTTPClient) -> None:
        self.http = http_client

    async def emit_event(self, event: dict[str, Any], request_id: str | None = None, trace_id: str | None = None) -> dict[str, Any]:
        # TODO: 接内部观测平台，补充采样、脱敏、span id 和资源标签。
        return await self.http.post_json("/observability/events", payload=event, request_id=request_id, trace_id=trace_id)

    async def emit_trace_span(self, span: dict[str, Any], request_id: str | None = None, trace_id: str | None = None) -> dict[str, Any]:
        # TODO: 接 OpenTelemetry collector 或内部 trace API，补充 span schema 映射。
        return await self.http.post_json("/observability/spans", payload=span, request_id=request_id, trace_id=trace_id)

