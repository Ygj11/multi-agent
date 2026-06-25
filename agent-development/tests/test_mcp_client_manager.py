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


@pytest.mark.asyncio
async def test_shutdown_closes_all_created_clients_once():
    clients = {}

    def factory(config):
        client = FakeMCPClient(config)
        clients[config.server_name] = client
        return client

    manager = MCPClientManager(settings=Settings(), server_configs=[_config()], client_factory=factory)
    await manager.initialize()

    await manager.shutdown()
    await manager.shutdown()

    assert clients["workflow"].close_calls == 1
    assert manager.clients == {}


@pytest.mark.asyncio
async def test_each_mcp_server_gets_a_distinct_client_instance():
    created = []

    def factory(config):
        client = FakeMCPClient(config)
        created.append(client)
        return client

    manager = MCPClientManager(
        settings=Settings(),
        server_configs=[_config("workflow", "mcp.workflow"), _config("audit", "mcp.audit")],
        client_factory=factory,
    )

    await manager.initialize()

    assert len(created) == 2
    assert manager.clients["workflow"] is not manager.clients["audit"]
    await manager.shutdown()
