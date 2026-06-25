from __future__ import annotations

"""In-memory registry of discovered MCP tools and server status."""

from datetime import UTC, datetime

from app.mcp.schemas import MCPServerStatus, MCPToolCapability


class MCPCapabilityRegistry:
    """Caches capabilities discovered from upstream MCP servers."""

    def __init__(self) -> None:
        """本地注册工具名 → MCPToolCapability  用于根据本地工具名查找远程归属。"""
        self._tools: dict[str, MCPToolCapability] = {}
        """server_name → 该服务器拥有的工具名称集合  用于按服务器查询所有工具"""
        self._tools_by_server: dict[str, set[str]] = {}
        """server_name → MCPServerStatus  用于保存服务器可用性和错误状态"""
        self._statuses: dict[str, MCPServerStatus] = {}

    def upsert_tools(self, server_name: str, tools: list[MCPToolCapability]) -> None:
        """Replace one server's tools with a fresh discovery result."""
        old_names = self._tools_by_server.get(server_name, set())
        for name in old_names:
            self._tools.pop(name, None)
        names: set[str] = set()
        for tool in tools:
            self._tools[tool.registered_tool_name] = tool
            names.add(tool.registered_tool_name)
        self._tools_by_server[server_name] = names
        self._statuses[server_name] = MCPServerStatus(
            server_name=server_name,
            available=True,
            last_error=None,
            last_refresh_at=_now(),
            tool_count=len(tools),
        )

    def list_tools(self) -> list[MCPToolCapability]:
        return sorted(self._tools.values(), key=lambda item: item.registered_tool_name)

    def get_tool(self, registered_tool_name: str) -> MCPToolCapability | None:
        return self._tools.get(registered_tool_name)

    def list_tools_by_server(self, server_name: str) -> list[MCPToolCapability]:
        names = self._tools_by_server.get(server_name, set())
        return sorted((self._tools[name] for name in names if name in self._tools), key=lambda item: item.registered_tool_name)

    def mark_server_unavailable(self, server_name: str, error: str) -> None:
        current = self._statuses.get(server_name)
        self._statuses[server_name] = MCPServerStatus(
            server_name=server_name,
            available=False,
            last_error=error,
            last_refresh_at=_now(),
            tool_count=current.tool_count if current else 0,
        )

    def get_server_statuses(self) -> list[MCPServerStatus]:
        return sorted(self._statuses.values(), key=lambda item: item.server_name)

    def get_server_status(self, server_name: str) -> MCPServerStatus | None:
        return self._statuses.get(server_name)


def _now() -> str:
    return datetime.now(UTC).isoformat()

