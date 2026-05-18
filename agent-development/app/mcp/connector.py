from __future__ import annotations

"""MCPConnector 抽象。

第三阶段仍不连接真实 MCP Server，但这里定义真实接入时需要保持的边界。
"""

from typing import Any


class MCPConnector:
    """外部 MCP 能力抽象。"""

    async def list_tools(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """列出 MCP 工具。"""
        raise NotImplementedError

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用 MCP 工具。"""
        raise NotImplementedError("Real MCP integration is not implemented in the first-stage MVP")
