from pathlib import Path
from typing import Any

import pytest

from app.agents.card_loader import AgentCardLoader
from app.integrations.base_http_client import BaseIntegrationHTTPClient
from app.integrations.clients import IntegrationClients
from app.integrations.troubleshooting_api_client import TroubleshootingAPIClient
from app.llm.schemas import LLMResponse
from app.mcp.schemas import MCPToolCapability
from app.schemas.agent_card import AgentCard
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.tools.agent_tools import register_agent_private_tools
from app.tools.executor import ToolExecutor
from app.tools.public_tools import register_public_tools
from app.tools.registry import ToolRegistry
from tests.fakes.fake_knowledge_service import FakeKnowledgeService


INTERNAL_SCHEMA_FIELDS = {
    "scope",
    "source",
    "is_write",
    "enabled",
    "agent_name",
    "server_name",
    "original_tool_name",
    "original_name",
    "callable",
    "metadata",
}


async def _sample_tool(value: str = "") -> dict[str, Any]:
    return {"value": value}


def _assert_openai_schema(schema: dict[str, Any], name: str | None = None) -> None:
    assert schema["type"] == "function"
    assert isinstance(schema["function"], dict)
    if name is not None:
        assert schema["function"]["name"] == name
    assert schema["function"]["description"]
    parameters = schema["function"]["parameters"]
    assert parameters["type"] == "object"
    assert isinstance(parameters["properties"], dict)
    assert isinstance(parameters["required"], list)
    serialized = str(schema)
    for field in INTERNAL_SCHEMA_FIELDS:
        assert field not in serialized


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_public_tools(registry, FakeKnowledgeService())
    register_agent_private_tools(registry)
    return registry


def _card(name: str):
    return AgentCardLoader(Path("app/agents/cards")).get_agent_card(name)


def test_register_public_and_private_support_explicit_parameters():
    registry = ToolRegistry()
    params = {
        "type": "object",
        "properties": {"value": {"type": "string", "description": "Value to echo."}},
        "required": ["value"],
    }

    registry.register_public("public_tool", _sample_tool, "Public tool.", parameters=params)
    registry.register_private(
        agent_name="agent_a",
        name="private_tool",
        tool=_sample_tool,
        description="Private tool.",
        parameters=params,
    )

    public_schema = registry.get_tool_schema("public_tool")
    private_schema = registry.get_tool_schema("private_tool")

    _assert_openai_schema(public_schema, "public_tool")
    _assert_openai_schema(private_schema, "private_tool")
    assert public_schema["function"]["parameters"]["required"] == ["value"]
    assert private_schema["function"]["parameters"]["required"] == ["value"]


def test_private_tool_schemas_include_descriptions_and_required_parameters():
    registry = _registry()

    expectations = {
        "query_task_status": ["request_id"],
        "query_endo_task_record": ["apply_seq"],
        "notice_policy_update": ["apply_seq", "policyNo", "endorseType"],
        "notice_customer_update": ["apply_seq", "policyNo", "endorseType"],
        "notice_period_update": ["apply_seq", "policyNo", "endorseType"],
        "policy_suspendOrRecovery": ["handleType", "premHandleFlag", "reqList"],
        "notice_finance": ["apply_seq", "policyNo", "endorseType"],
    }
    for tool_name, required in expectations.items():
        schema = registry.get_tool_schema(tool_name)
        _assert_openai_schema(schema, tool_name)
        assert schema["function"]["parameters"]["required"] == required

    for mock_tool in (
        "notice_policy_update",
        "notice_customer_update",
        "notice_period_update",
        "policy_suspendOrRecovery",
        "notice_finance",
    ):
        assert registry.get_definition(mock_tool).is_write is False


def test_troubleshooting_real_mode_registers_write_tools_as_write():
    registry = ToolRegistry()
    register_agent_private_tools(
        registry,
        troubleshooting_tool_mode="real",
        integration_clients=IntegrationClients(
            troubleshooting=TroubleshootingAPIClient(
                BaseIntegrationHTTPClient(base_url="https://troubleshooting.example.test")
            )
        ),
    )

    for write_tool in (
        "notice_policy_update",
        "notice_customer_update",
        "notice_period_update",
        "policy_suspendOrRecovery",
        "notice_finance",
    ):
        assert registry.get_definition(write_tool).is_write is True


def test_real_tool_modes_require_injected_real_clients():
    with pytest.raises(ValueError, match="POS_TOOL_MODE=real requires a configured PosAPIClient"):
        register_agent_private_tools(ToolRegistry(), pos_tool_mode="real")

    with pytest.raises(ValueError, match="TROUBLESHOOTING_TOOL_MODE=real requires a configured TroubleshootingAPIClient"):
        register_agent_private_tools(ToolRegistry(), troubleshooting_tool_mode="real")


def test_public_knowledge_tools_have_query_schema():
    registry = _registry()

    for tool_name in ("rag_search_tool",):
        schema = registry.get_tool_schema(tool_name)
        _assert_openai_schema(schema, tool_name)
        assert "query" in schema["function"]["parameters"]["required"]
        assert "query" in schema["function"]["parameters"]["properties"]


def test_mcp_tools_are_exposed_as_openai_function_schema_without_internal_fields():
    capability = MCPToolCapability(
        registered_tool_name="mcp.workflow.query_refund_task",
        description="Query refund workflow task.",
        input_schema={
            "type": "object",
            "properties": {"request_id": {"type": "string", "description": "Request id."}},
            "required": ["request_id"],
        },
        server_name="workflow",
        original_tool_name="query_refund_task",
    )
    registry = ToolRegistry()
    registry.register_mcp_tools([capability])

    schema = registry.get_tool_schema("mcp.workflow.query_refund_task")

    _assert_openai_schema(schema, "mcp.workflow.query_refund_task")
    assert schema["function"]["description"] == "Query refund workflow task."
    assert schema["function"]["parameters"]["required"] == ["request_id"]

    definition = registry.get_definition("mcp.workflow.query_refund_task")
    assert definition.source == "mcp"
    assert definition.server_name == "workflow"
    assert definition.original_name == "query_refund_task"
    assert definition.metadata["server_name"] == "workflow"
    assert definition.metadata["original_tool_name"] == "query_refund_task"


def test_mcp_array_parameter_schema_is_preserved_for_batch_entity_queries():
    capability = MCPToolCapability(
        registered_tool_name="mcp.workflow.query_insureds",
        description="Query insured people for multiple policies.",
        input_schema={
            "type": "object",
            "properties": {
                "policy_no": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "保单号列表。",
                }
            },
            "required": ["policy_no"],
        },
        server_name="workflow",
        original_tool_name="query_insureds",
    )
    registry = ToolRegistry()
    registry.register_mcp_tools([capability])

    schema = registry.get_tool_schema("mcp.workflow.query_insureds")

    assert schema["function"]["parameters"]["properties"]["policy_no"] == {
        "type": "array",
        "items": {"type": "string"},
        "description": "保单号列表。",
    }


def test_agent_visible_tool_schemas_are_standard_and_authorized_only():
    registry = _registry()
    card = AgentCard(
        agent_name="troubleshooting_agent",
        display_name="Troubleshooting Agent",
        description="Troubleshooting.",
        capabilities=["troubleshooting"],
        supported_intents=["troubleshooting"],
        required_entities=[],
        output_schema="SubAgentResult",
        private_tools=["query_internal_log"],
        public_tools_allowed=True,
        skills=["troubleshooting_agent.refund_failure"],
        rag_namespaces=[],
        enabled=True,
        version="1",
    )
    registry.get_definition("calculator_tool").enabled = False

    schemas = registry.list_tools_for_agent(card)
    names = {schema["function"]["name"] for schema in schemas}

    assert {"query_internal_log", "rag_search_tool"}.issubset(names)
    assert "query_task_status" not in names
    assert "calculator_tool" not in names
    for schema in schemas:
        _assert_openai_schema(schema)


@pytest.mark.asyncio
async def test_tool_executor_validates_missing_required_arguments_before_execution_or_approval():
    executor = ToolExecutor(_registry())

    public_result = await executor.execute(
        agent_name="troubleshooting_agent",
        agent_card=_card("troubleshooting_agent"),
        tool_name="rag_search_tool",
        arguments={},
    )
    private_result = await executor.execute(
        agent_name="troubleshooting_agent",
        agent_card=_card("troubleshooting_agent"),
        tool_name="query_task_status",
        arguments={},
    )
    write_result = await executor.execute(
        agent_name="troubleshooting_agent",
        agent_card=_card("troubleshooting_agent"),
        tool_name="notice_policy_update",
        arguments={"apply_seq": "APPLY123", "policyNo": "9201344266"},
    )

    assert public_result.success is False
    assert public_result.error == "missing_required_argument:query"
    assert private_result.success is False
    assert private_result.error == "missing_required_argument:request_id"
    assert write_result.success is False
    assert write_result.error == "missing_required_argument:endorseType"
    assert write_result.needs_human_approval is False


@pytest.mark.asyncio
async def test_tool_calling_runner_passes_openai_tool_schemas_to_llm():
    class CapturingLLM:
        def __init__(self) -> None:
            self.tools = None

        async def chat(self, messages, tools=None, **kwargs):
            self.tools = tools
            return LLMResponse(content="done", has_tool_calls=False)

    registry = ToolRegistry()
    registry.register_private(
        agent_name="agent_a",
        name="tool1",
        tool=_sample_tool,
        description="Sample tool.",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string", "description": "Value."}},
            "required": ["value"],
        },
    )
    card = AgentCard(
        agent_name="agent_a",
        display_name="Agent A",
        description="test",
        capabilities=["test"],
        supported_intents=["test"],
        required_entities=[],
        output_schema="SubAgentResult",
        private_tools=["tool1"],
        public_tools_allowed=False,
        skills=["agent_a.default"],
        rag_namespaces=[],
        enabled=True,
        version="1",
    )
    llm = CapturingLLM()
    runner = ToolCallingRunner(llm_provider=llm, tool_executor=ToolExecutor(registry))
    tools = registry.list_tools_for_agent(card)

    await runner.run(
        agent_name="agent_a",
        agent_card=card,
        messages=[{"role": "user", "content": "go"}],
        tools=tools,
        session_key="s",
        request_id="r",
    )

    assert isinstance(llm.tools, list)
    assert llm.tools
    for schema in llm.tools:
        _assert_openai_schema(schema)
