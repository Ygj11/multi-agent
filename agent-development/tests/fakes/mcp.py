from __future__ import annotations

from typing import Any

from app.mcp.schemas import MCPServerConfig, MCPToolCapability


class FakeMCPClient:
    """Test-only MCP client fake. Do not import from app code."""

    def __init__(self, config: MCPServerConfig, *, fail_initialize: bool = False) -> None:
        self.config = config
        self.fail_initialize = fail_initialize
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.close_calls = 0

    async def initialize(self) -> None:
        if self.fail_initialize:
            raise RuntimeError("init failed")

    async def list_tools(self) -> list[MCPToolCapability]:
        prefix = self.config.tool_name_prefix or f"mcp.{self.config.server_name}"
        return [
            MCPToolCapability(
                server_name=self.config.server_name,
                original_tool_name="query_refund_task",
                registered_tool_name=f"{prefix}.query_refund_task",
                description="query refund workflow task",
                input_schema={"type": "object", "properties": {"policy_no": {"type": "string"}}},
            )
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool_name, arguments))
        return {"success": True, "tool_name": tool_name, "arguments": arguments}

    async def health_check(self) -> bool:
        return not self.fail_initialize

    async def close(self) -> None:
        self.close_calls += 1


class FakeMCPClientManager:
    """Test-only manager fake for ToolExecutor and Agent loop tests."""

    def __init__(self, *, mode: str = "success") -> None:
        self.mode = mode
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, registered_tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from app.mcp.errors import MCPServerUnavailableError, MCPToolError, MCPToolTimeoutError

        self.calls.append((registered_tool_name, arguments))
        if self.mode == "unavailable":
            raise MCPServerUnavailableError("down")
        if self.mode == "timeout":
            raise MCPToolTimeoutError("slow")
        if self.mode == "error":
            raise MCPToolError("boom")
        return {"success": True, "registered_tool_name": registered_tool_name, "arguments": arguments}
