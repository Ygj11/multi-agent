from __future__ import annotations

"""HTTP MCP client implementation."""

from typing import Any, Protocol

import httpx

from app.mcp.schemas import MCPServerConfig, MCPToolCapability
from app.mcp.tool_adapter import capability_from_raw_tool
from app.runtime.async_client_lifecycle import AsyncClientLifecycle


class MCPClient(Protocol):
    """MCPClientManager 依赖的最小客户端协议。

    不同传输方式可以实现同一协议；调用方只关心 initialize/list_tools/call_tool
    和 close 生命周期。
    """

    async def initialize(self) -> None:
        ...

    async def list_tools(self) -> list[MCPToolCapability]:
        ...

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        ...

    async def health_check(self) -> bool:
        ...

    async def close(self) -> None:
        """释放该 MCP 客户端持有的网络资源。"""
        ...


class HTTPMCPClient:
    """轻量 HTTP MCP client。

    每个 MCP server 拥有独立 client 生命周期，避免不同 base_url/timeout/auth
    的上游共用同一连接池。工具执行时仍由 ToolExecutor 统一做安全守卫。
    """

    def __init__(
        self,
        config: MCPServerConfig,
        client: httpx.AsyncClient | None = None,
        *,
        owns_client: bool = False,
    ) -> None:
        self.config = config
        if not config.url:
            raise ValueError(f"MCP server {config.server_name} requires url for http transport")
        self._client_lifecycle = AsyncClientLifecycle(
            factory=lambda: httpx.AsyncClient(timeout=self.config.timeout),
            close_client=lambda value: value.aclose(),
            client=client,
            owns_client=owns_client,
        )

    async def initialize(self) -> None:
        await self._post({"jsonrpc": "2.0", "id": "initialize", "method": "initialize", "params": {}})

    async def list_tools(self) -> list[MCPToolCapability]:
        """List MCP tool capabilities. 兼容多种模式获取"""
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
        """mcp tool call, result convert"""
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

    async def close(self) -> None:
        """关闭自有连接池；外部注入 client 的关闭权留在调用方。"""
        await self._client_lifecycle.close()

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._client_lifecycle.lease() as client:
                response = await client.post(str(self.config.url), json=payload)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("MCP response must be a JSON object")
            return data
        except httpx.TimeoutException as exc:
            raise TimeoutError(str(exc)) from exc

    async def _get_client(self) -> httpx.AsyncClient:
        """仅供测试断言当前 client；生产请求通过 lease() 借用。"""
        return await self._client_lifecycle.get_client_for_testing()
