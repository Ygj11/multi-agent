from __future__ import annotations

"""Example client for a future external tool execution audit service."""

from typing import Any

from app.integrations.base_http_client import BaseIntegrationHTTPClient


class AuditAPIClient:
    """Future replacement for local SQLite tool_execution_logs storage."""

    def __init__(self, http_client: BaseIntegrationHTTPClient) -> None:
        self.http = http_client

    async def write_tool_execution_log(
        self,
        payload: dict[str, Any],
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.http.post_json(
            "/audit/tool-executions",
            payload=payload,
            request_id=request_id,
            trace_id=trace_id,
        )

    async def query_tool_execution_logs(
        self,
        session_key: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        data = await self.http.get_json(
            "/audit/tool-executions",
            params={"session_key": session_key},
            request_id=request_id,
            trace_id=trace_id,
        )
        return list(data.get("logs", []))
