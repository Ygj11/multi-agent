from __future__ import annotations

"""未来真实 MCP HTTP client 示例。"""

from typing import Any

from app.integrations.base_http_client import BaseIntegrationHTTPClient


class MCPHTTPClient:
    """Example future HTTP client for an MCP gateway."""

    def __init__(self, http_client: BaseIntegrationHTTPClient) -> None:
        self.http = http_client

    async def list_tools(self, request_id: str | None = None, trace_id: str | None = None) -> list[dict[str, Any]]:
        # TODO: 按真实 MCP 协议映射 list_tools、鉴权和 tool schema。
        data = await self.http.get_json("/mcp/tools", request_id=request_id, trace_id=trace_id)
        return list(data.get("tools", []))

    async def call_tool(self, tool_name: str, arguments: dict[str, Any], request_id: str | None = None, trace_id: str | None = None) -> dict[str, Any]:
        # TODO: 按真实 MCP 协议映射 call_tool，并对 arguments 做生产级脱敏和审计。
        return await self.http.post_json(
            "/mcp/tools/call",
            payload={"tool_name": tool_name, "arguments": arguments},
            request_id=request_id,
            trace_id=trace_id,
        )
