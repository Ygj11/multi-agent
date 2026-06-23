from __future__ import annotations

import pytest

from app.bootstrap.container import build_app_container
from app.config.settings import Settings
from app.integrations.pos_api_client import PosAPIClient
from app.integrations.troubleshooting_api_client import TroubleshootingAPIClient
from app.main import create_app
from app.mcp.schemas import MCPToolCapability
from app.schemas.agent_card import MCPPolicy


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
    assert container.pos_api_client is None
    assert container.troubleshooting_api_client is None


def test_app_container_builds_real_clients_only_for_real_tool_modes(tmp_path):
    container = build_app_container(
        _settings(
            pos_tool_mode="real",
            troubleshooting_tool_mode="real",
            troubleshooting_api_base_url="https://troubleshooting.example.test",
        ),
        sqlite_db_path=tmp_path / "real-clients.sqlite3",
    )

    assert isinstance(container.pos_api_client, PosAPIClient)
    assert isinstance(container.troubleshooting_api_client, TroubleshootingAPIClient)
    assert container.pos_api_client.http.base_url == "http://ehis-epos-gateway.paic.com.cn"
    assert container.troubleshooting_api_client.http.base_url == "https://troubleshooting.example.test"


@pytest.mark.asyncio
async def test_app_container_startup_and_shutdown_are_idempotent(tmp_path):
    container = build_app_container(_settings(), sqlite_db_path=tmp_path / "lifecycle.sqlite3")

    await container.startup()
    await container.startup()
    assert container.started is True

    await container.shutdown()
    await container.shutdown()
    assert container.started is False


@pytest.mark.asyncio
async def test_app_container_startup_failure_does_not_mark_started(tmp_path, monkeypatch):
    container = build_app_container(
        _settings(enable_mcp_client=True, mcp_servers_json=None),
        sqlite_db_path=tmp_path / "startup-failure.sqlite3",
    )

    def fail_contract_validation(*, strict: bool = False):
        raise RuntimeError("contract validation failed")

    monkeypatch.setattr(container.tool_registry, "validate_contracts", fail_contract_validation)

    with pytest.raises(RuntimeError, match="contract validation failed"):
        await container.startup()

    assert container.started is False


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
