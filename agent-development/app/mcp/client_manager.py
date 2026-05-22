from __future__ import annotations

"""Manager for upstream MCP clients and discovered capabilities."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

from app.config.settings import Settings
from app.mcp.capability_registry import MCPCapabilityRegistry
from app.mcp.client import HTTPMCPClient, MCPClient
from app.mcp.errors import MCPServerUnavailableError, MCPToolError, MCPToolTimeoutError
from app.mcp.schemas import MCPServerConfig, MCPServerStatus
from app.observability.logger import log_event


ClientFactory = Callable[[MCPServerConfig], MCPClient]


class MCPClientManager:
    """Creates MCP clients, refreshes capabilities, and routes tool calls."""

    def __init__(
        self,
        *,
        settings: Settings,
        capability_registry: MCPCapabilityRegistry | None = None,
        client_factory: ClientFactory | None = None,
        server_configs: list[MCPServerConfig] | None = None,
    ) -> None:
        self.settings = settings
        self.capability_registry = capability_registry or MCPCapabilityRegistry()
        self.server_configs = server_configs if server_configs is not None else parse_mcp_server_configs(settings.mcp_servers_json)
        self.client_factory = client_factory or self._default_client_factory
        self.clients: dict[str, MCPClient] = {}

    async def initialize(self) -> None:
        """Initialize enabled servers and discover tools without failing app startup."""
        for config in self.server_configs:
            if not config.enabled:
                continue
            try:
                client = self.client_factory(config)
                self.clients[config.server_name] = client
                await client.initialize()
                tools = await client.list_tools()
                self.capability_registry.upsert_tools(config.server_name, tools)
                log_event(
                    "mcp_server_initialized",
                    node="mcp_client_manager",
                    message="MCP server initialized",
                    data={"server_name": config.server_name, "tool_count": len(tools)},
                )
            except Exception as exc:
                self.capability_registry.mark_server_unavailable(config.server_name, str(exc))
                log_event(
                    "mcp_server_unavailable",
                    level="WARNING",
                    node="mcp_client_manager",
                    message="MCP server unavailable during initialize",
                    data={"server_name": config.server_name, "error": str(exc)},
                )

    async def refresh_capabilities(self) -> None:
        """Refresh capabilities. Failed servers keep previous tool cache."""
        for config in self.server_configs:
            if not config.enabled:
                continue
            client = self.clients.get(config.server_name)
            try:
                if client is None:
                    client = self.client_factory(config)
                    self.clients[config.server_name] = client
                    await client.initialize()
                tools = await client.list_tools()
                self.capability_registry.upsert_tools(config.server_name, tools)
            except Exception as exc:
                self.capability_registry.mark_server_unavailable(config.server_name, str(exc))

    async def call_tool(self, registered_tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Route a registered MCP tool call to its owning server."""
        capability = self.capability_registry.get_tool(registered_tool_name)
        if capability is None:
            raise MCPToolError(f"unknown_mcp_tool:{registered_tool_name}")
        status = self.capability_registry.get_server_status(capability.server_name)
        if status is not None and not status.available:
            raise MCPServerUnavailableError(status.last_error or f"mcp_server_unavailable:{capability.server_name}")
        client = self.clients.get(capability.server_name)
        if client is None:
            raise MCPServerUnavailableError(f"mcp_server_unavailable:{capability.server_name}")
        try:
            return await client.call_tool(capability.original_tool_name, arguments)
        except asyncio.TimeoutError as exc:
            raise MCPToolTimeoutError(str(exc)) from exc
        except MCPServerUnavailableError:
            raise
        except MCPToolTimeoutError:
            raise
        except Exception as exc:
            raise MCPToolError(str(exc)) from exc

    def get_server_statuses(self) -> list[MCPServerStatus]:
        return self.capability_registry.get_server_statuses()

    @staticmethod
    def _default_client_factory(config: MCPServerConfig) -> MCPClient:
        if config.transport.lower() not in {"http", "sse"}:
            raise ValueError(f"unsupported_mcp_transport:{config.transport}")
        return HTTPMCPClient(config)


def parse_mcp_server_configs(raw: str | None) -> list[MCPServerConfig]:
    """Parse MCP_SERVERS_JSON/MCP_SERVERS as JSON. YAML is a future extension."""
    if not raw:
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("MCP_SERVERS_JSON must be a JSON array")
    return [MCPServerConfig(**item) for item in data]

