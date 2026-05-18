from __future__ import annotations

"""MCP 工具 wrapper。

子 Agent 只能通过 ToolBroker 调用这里注册的 wrapper，wrapper 再调用 MCPConnector。
"""

from typing import Any

from app.mcp.connector import MCPConnector


def build_mcp_tool(connector: MCPConnector, tool_name: str):
    """构造 ToolRegistry 可注册的 MCP 工具函数。"""

    async def call_mcp_tool(**arguments: Any) -> dict[str, Any]:
        """通过 MCPConnector 调用指定 MCP 工具。"""
        return await connector.call_tool(tool_name=tool_name, arguments=arguments)

    return call_mcp_tool
