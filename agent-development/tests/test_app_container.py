from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.container import build_app_container
from app.config.settings import Settings
from app.integrations.clients import IntegrationClients
from app.integrations.pos_api_client import PosAPIClient
from app.integrations.troubleshooting_api_client import TroubleshootingAPIClient
from app.main import create_app
from app.mcp.schemas import MCPToolCapability
from app.mcp.schemas import MCPServerConfig
from app.schemas.agent_card import MCPPolicy
from tests.fakes.mcp import FakeMCPClient


def _settings(**overrides):
    data = {
        "enable_mcp_client": False,
        "pos_tool_mode": "mock",
        "troubleshooting_tool_mode": "mock",
        "app_env": "local",
    }
    data.update(overrides)
    return Settings(**data)


def test_build_app_container_wires_runtime_components(tmp_path):
    container = build_app_container(_settings(), sqlite_db_path=tmp_path / "container.sqlite3")

    assert container.orchestrator is not None
    assert container.graph is not None
    assert container.approval_service.orchestrator is container.orchestrator
    assert container.tool_executor.registry is container.tool_registry
    assert container.tool_calling_runner.tool_executor is container.tool_executor
    assert set(container.subagent_manager.list_agents()) == {"pos_query_agent", "troubleshooting_agent"}
    assert "rag_search_tool" in container.tool_registry.list_public_tools()
    assert "query_endo_task_record" in container.tool_registry.list_private_tools("troubleshooting_agent")
    assert container.started is False
    assert container.integration_clients == IntegrationClients()


def test_integration_clients_reference_set_is_read_only():
    clients = IntegrationClients()

    with pytest.raises(FrozenInstanceError):
        clients.pos = None


def test_app_container_builds_real_clients_only_for_real_tool_modes(tmp_path):
    container = build_app_container(
        _settings(
            pos_tool_mode="real",
            troubleshooting_tool_mode="real",
            troubleshooting_api_base_url="https://troubleshooting.example.test",
        ),
        sqlite_db_path=tmp_path / "real-clients.sqlite3",
    )

    assert isinstance(container.integration_clients.pos, PosAPIClient)
    assert isinstance(container.integration_clients.troubleshooting, TroubleshootingAPIClient)
    assert container.integration_clients.pos.http.base_url == "http://ehis-epos-gateway.paic.com.cn"
    assert container.integration_clients.troubleshooting.http.base_url == "https://troubleshooting.example.test"


@pytest.mark.asyncio
async def test_app_container_startup_and_shutdown_are_idempotent(tmp_path):
    container = build_app_container(_settings(), sqlite_db_path=tmp_path / "lifecycle.sqlite3")

    await container.startup()
    await container.startup()
    assert container.started is True

    await container.shutdown()
    await container.shutdown()
    assert container.started is False
    assert container.closed is True


@pytest.mark.asyncio
async def test_app_container_shutdown_closes_real_integration_client(tmp_path):
    container = build_app_container(
        _settings(pos_tool_mode="real", pos_api_base_url="https://pos.example.test"),
        sqlite_db_path=tmp_path / "close-real-client.sqlite3",
    )
    await container.startup()
    assert container.integration_clients.pos is not None
    http_client = await container.integration_clients.pos.http._get_client()

    await container.shutdown()

    assert http_client.is_closed is True
    with pytest.raises(RuntimeError, match="client lifecycle is closed"):
        await container.integration_clients.pos.http._get_client()


@pytest.mark.asyncio
async def test_app_container_startup_failure_does_not_mark_started(tmp_path, monkeypatch):
    container = build_app_container(
        _settings(enable_mcp_client=True, mcp_servers_json=None),
        sqlite_db_path=tmp_path / "startup-failure.sqlite3",
    )

    shutdown_calls = 0

    def fail_contract_validation(*, strict: bool = False):
        raise RuntimeError("contract validation failed")

    async def record_shutdown():
        nonlocal shutdown_calls
        shutdown_calls += 1

    monkeypatch.setattr(container.tool_registry, "validate_contracts", fail_contract_validation)
    monkeypatch.setattr(container.mcp_client_manager, "shutdown", record_shutdown)

    with pytest.raises(RuntimeError, match="contract validation failed"):
        await container.startup()

    assert container.started is False
    assert container.closed is True
    assert shutdown_calls == 1


@pytest.mark.asyncio
async def test_startup_failure_closes_mcp_client_created_before_contract_validation(tmp_path, monkeypatch):
    container = build_app_container(
        _settings(enable_mcp_client=True),
        sqlite_db_path=tmp_path / "startup-failure-closes-mcp.sqlite3",
    )
    created = []
    container.mcp_client_manager.server_configs = [
        MCPServerConfig(server_name="workflow", enabled=True, transport="http", url="https://mcp.example.test")
    ]

    def factory(config):
        client = FakeMCPClient(config)
        created.append(client)
        return client

    def fail_contract_validation(*, strict: bool = False):
        raise RuntimeError("contract validation failed")

    container.mcp_client_manager.client_factory = factory
    monkeypatch.setattr(container.tool_registry, "validate_contracts", fail_contract_validation)

    with pytest.raises(RuntimeError, match="contract validation failed"):
        await container.startup()

    assert created[0].close_calls == 1
    assert container.started is False
    assert container.closed is True


@pytest.mark.asyncio
async def test_container_continues_closing_resources_after_one_close_failure(tmp_path, monkeypatch):
    container = build_app_container(_settings(), sqlite_db_path=tmp_path / "close-failure.sqlite3")
    closed = []

    async def failing_close():
        raise RuntimeError("tool close failed")

    class ClosingResource:
        async def close(self):
            closed.append("approval")

    monkeypatch.setattr(container.tool_registry, "close", failing_close)
    container.approval_service.client = ClosingResource()
    await container.startup()

    await container.shutdown()

    assert closed == ["approval"]


def test_fastapi_lifespan_closes_container_resources(tmp_path, monkeypatch):
    container = build_app_container(_settings(), sqlite_db_path=tmp_path / "lifespan.sqlite3")
    closed = []

    class ClosingResource:
        async def close(self):
            closed.append("pos")

    container.integration_clients = IntegrationClients(pos=ClosingResource())
    monkeypatch.setattr("app.main.build_app_container", lambda settings, sqlite_db_path=None: container)
    from app.main import create_app

    with TestClient(create_app(sqlite_db_path=tmp_path / "lifespan.sqlite3")):
        assert container.started is True

    assert container.closed is True
    assert closed == ["pos"]


@pytest.mark.asyncio
async def test_mcp_startup_registers_dynamic_tools_into_existing_runtime(tmp_path, monkeypatch):
    container = build_app_container(
        _settings(enable_mcp_client=True, mcp_servers_json=None),
        sqlite_db_path=tmp_path / "mcp-startup.sqlite3",
    )
    initialize_calls = 0

    async def fake_initialize():
        nonlocal initialize_calls
        initialize_calls += 1
        container.mcp_capability_registry.upsert_tools(
            "workflow",
            [
                MCPToolCapability(
                    server_name="workflow",
                    original_tool_name="query_dynamic",
                    registered_tool_name="mcp.workflow.query_dynamic",
                    description="dynamic workflow query",
                    input_schema={
                        "type": "object",
                        "properties": {"apply_seq": {"type": "string"}},
                        "required": ["apply_seq"],
                    },
                    raw_schema={"metadata": {"operation": "read", "risk_level": "low"}},
                )
            ],
        )

    monkeypatch.setattr(container.mcp_client_manager, "initialize", fake_initialize)

    assert container.tool_registry.get_definition("mcp.workflow.query_dynamic") is None
    await container.startup()
    await container.startup()

    definition = container.tool_registry.get_definition("mcp.workflow.query_dynamic")
    assert definition is not None
    assert definition.source == "mcp"
    assert initialize_calls == 1
    assert container.tool_executor.registry is container.tool_registry

    card = container.agent_card_loader.get_agent_card("troubleshooting_agent")
    mcp_card = card.model_copy(update={"mcp_policy": MCPPolicy(enabled=True)})
    assert "mcp.workflow.query_dynamic" in container.tool_registry.list_available_tools_for_agent(
        mcp_card.agent_name,
        mcp_card,
    )


def test_create_app_mounts_only_container_state(tmp_path):
    app = create_app(sqlite_db_path=tmp_path / "app.sqlite3")
    container = app.state.container

    assert vars(app.state)["_state"] == {"container": container}
    assert container.orchestrator is not None
    assert container.approval_service is not None
    assert container.tool_registry is not None
    assert container.tool_executor is not None
    assert container.skill_catalog is not None
    assert container.agent_card_loader is not None
    assert container.storage.db is not None
