import pytest

from app.bootstrap.tools import register_admin_restricted_tools
from app.config.settings import Settings
from app.integrations.base_http_client import BaseIntegrationHTTPClient
from app.integrations.clients import IntegrationClients
from app.integrations.troubleshooting_api_client import TroubleshootingAPIClient
from app.mcp.schemas import MCPToolCapability
from app.tools.agent_tools import register_agent_private_tools
from app.tools.contracts import ToolContract, ToolContractCatalog
from app.tools.public_tools import register_public_tools
from app.tools.registry import ToolRegistry
from tests.fakes.fake_knowledge_service import FakeKnowledgeService


async def _ok_tool(**kwargs):
    return {"success": True}


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_public_tools(registry, FakeKnowledgeService())
    register_agent_private_tools(
        registry,
        troubleshooting_tool_mode="real",
        integration_clients=IntegrationClients(
            troubleshooting=TroubleshootingAPIClient(
                BaseIntegrationHTTPClient(base_url="https://troubleshooting.example.test")
            )
        ),
    )
    register_admin_restricted_tools(registry, Settings())
    return registry


def test_all_current_registered_tools_have_contracts():
    registry = _full_registry()

    assert registry.validate_contracts(strict=False) == []
    for name in registry.list_tools():
        assert registry.get_definition(name).contract is not None


def test_prod_strict_contract_validation_fails_for_missing_contract():
    registry = ToolRegistry()
    registry.register_public("local_uncontracted_tool", _ok_tool)

    with pytest.raises(ValueError, match="tool missing contract: local_uncontracted_tool"):
        registry.validate_contracts(strict=True, check_unknown=False)


def test_contract_catalog_rejects_unknown_tool_references():
    catalog = ToolContractCatalog(
        version="1.0.0",
        tools={
            "ghost_tool": ToolContract(
                tool_name="ghost_tool",
                timeout_ms=1000,
                result_schema="AnyDictResult",
            )
        },
    )
    registry = ToolRegistry(contract_catalog=catalog)

    assert registry.validate_contracts(check_unknown=True) == ["contract references unknown tool: ghost_tool"]


def test_contract_validation_rejects_unknown_result_schema():
    catalog = ToolContractCatalog(
        version="1.0.0",
        tools={
            "bad_schema_tool": ToolContract(
                tool_name="bad_schema_tool",
                timeout_ms=1000,
                result_schema="MissingResultSchema",
            )
        },
    )
    registry = ToolRegistry(contract_catalog=catalog)
    registry.register_public("bad_schema_tool", _ok_tool)

    assert registry.validate_contracts(check_unknown=False) == [
        "bad_schema_tool references unknown result_schema: MissingResultSchema"
    ]


def test_mcp_tools_receive_default_contract():
    registry = ToolRegistry()
    registry.register_mcp_tools(
        [
            MCPToolCapability(
                server_name="workflow",
                original_tool_name="query_refund_task",
                registered_tool_name="mcp.workflow.query_refund_task",
                description="query refund",
                input_schema={"type": "object", "properties": {}},
            )
        ]
    )

    definition = registry.get_definition("mcp.workflow.query_refund_task")
    assert definition.contract is not None
    assert definition.contract.tool_name == "mcp.workflow.query_refund_task"
    assert definition.contract.result_schema == "AnyDictResult"
