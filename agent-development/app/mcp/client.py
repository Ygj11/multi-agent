from __future__ import annotations

"""HTTP MCP client implementation."""

import asyncio
from typing import Any, Protocol

import httpx

from app.mcp.schemas import MCPServerConfig, MCPToolCapability
from app.mcp.tool_adapter import capability_from_raw_tool


class MCPClient(Protocol):
    """MCP client boundary used by MCPClientManager."""

    async def initialize(self) -> None:
        ...

    async def list_tools(self) -> list[MCPToolCapability]:
        ...

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        ...

    async def health_check(self) -> bool:
        ...


class HTTPMCPClient:
    """Small JSON-RPC-ish HTTP MCP client.

    Stdio/SSE can be added behind the same protocol later. The current HTTP
    implementation intentionally accepts a few common response shapes so local
    tests and lightweight mock MCP services are easy to wire.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        if not config.url:
            raise ValueError(f"MCP server {config.server_name} requires url for http transport")

    async def initialize(self) -> None:
        await self._post({"jsonrpc": "2.0", "id": "initialize", "method": "initialize", "params": {}})

    async def list_tools(self) -> list[MCPToolCapability]:
        data = await self._post({"jsonrpc": "2.0", "id": "tools/list", "method": "tools/list", "params": {}})
        tools = data.get("tools")
        if tools is None and isinstance(data.get("result"), dict):
            tools = data["result"].get("tools")
        if tools is None:
            tools = data.get("result", [])
        if not isinstance(tools, list):
            raise ValueError("MCP list_tools response did not contain a tools list")
        return [capability_from_raw_tool(self.config, item) for item in tools]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        data = await self._post(
            {
                "jsonrpc": "2.0",
                "id": f"tools/call:{tool_name}",
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
        )
        if "error" in data and data["error"]:
            return {"success": False, "error": data["error"]}
        result = data.get("result", data)
        if isinstance(result, dict):
            return result
        return {"success": True, "result": result}

    async def health_check(self) -> bool:
        try:
            await self.list_tools()
            return True
        except Exception:
            return False

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(str(self.config.url), json=payload)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("MCP response must be a JSON object")
            return data
        except httpx.TimeoutException as exc:
            raise asyncio.TimeoutError(str(exc)) from exc

