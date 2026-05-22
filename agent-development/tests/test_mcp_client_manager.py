import pytest

from app.config.settings import Settings
from app.mcp.client_manager import MCPClientManager
from app.mcp.errors import MCPToolError
from app.mcp.schemas import MCPServerConfig
from tests.fakes.mcp import FakeMCPClient


def _config(name="workflow", prefix="mcp.workflow"):
    return MCPServerConfig(server_name=name, enabled=True, transport="http", url="http://mcp", tool_name_prefix=prefix)


@pytest.mark.asyncio
async def test_initialize_success_lists_tools():
    clients = {}

    def factory(config):
        clients[config.server_name] = FakeMCPClient(config)
        return clients[config.server_name]

    manager = MCPClientManager(settings=Settings(), server_configs=[_config()], client_factory=factory)
    await manager.initialize()

    assert manager.capability_registry.get_tool("mcp.workflow.query_refund_task") is not None
    assert manager.get_server_statuses()[0].available is True


@pytest.mark.asyncio
async def test_one_server_failure_does_not_break_others():
    def factory(config):
        return FakeMCPClient(config, fail_initialize=config.server_name == "bad")

    configs = [_config("bad", "mcp.bad"), _config("workflow", "mcp.workflow")]
    manager = MCPClientManager(settings=Settings(), server_configs=configs, client_factory=factory)
    await manager.initialize()

    statuses = {status.server_name: status for status in manager.get_server_statuses()}
    assert statuses["bad"].available is False
    assert statuses["workflow"].available is True
    assert manager.capability_registry.get_tool("mcp.workflow.query_refund_task") is not None


@pytest.mark.asyncio
async def test_call_tool_routes_to_owning_server():
    clients = {}

    def factory(config):
        clients[config.server_name] = FakeMCPClient(config)
        return clients[config.server_name]

    manager = MCPClientManager(settings=Settings(), server_configs=[_config()], client_factory=factory)
    await manager.initialize()
    result = await manager.call_tool("mcp.workflow.query_refund_task", {"policy_no": "9201344266"})

    assert result["success"] is True
    assert clients["workflow"].calls == [("query_refund_task", {"policy_no": "9201344266"})]


@pytest.mark.asyncio
async def test_unknown_registered_tool_name_returns_error():
    manager = MCPClientManager(settings=Settings(), server_configs=[_config()], client_factory=lambda config: FakeMCPClient(config))
    await manager.initialize()

    with pytest.raises(MCPToolError):
        await manager.call_tool("mcp.workflow.unknown", {})
