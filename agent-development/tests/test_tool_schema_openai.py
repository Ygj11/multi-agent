from pathlib import Path
from typing import Any

import pytest

from app.agents.card_loader import AgentCardLoader
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
        "query_policy_status": ["policy_no"],
        "update_policy_status": ["policy_no", "status"],
        "query_claim_progress": ["claim_no"],
    }
    for tool_name, required in expectations.items():
        schema = registry.get_tool_schema(tool_name)
        _assert_openai_schema(schema, tool_name)
        assert schema["function"]["parameters"]["required"] == required

    update_schema = registry.get_tool_schema("update_policy_status")
    assert "human approval" in update_schema["function"]["description"].lower()
    assert registry.get_definition("update_policy_status").is_write is True


def test_public_knowledge_tools_have_query_schema():
    registry = _registry()

    for tool_name in ("rag_search_tool", "get_knowledge"):
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


def test_agent_visible_tool_schemas_are_standard_and_authorized_only():
    registry = _registry()
    card = AgentCard(
        agent_name="policy_query_agent",
        display_name="Policy Query Agent",
        description="Policy query.",
        capabilities=["policy query"],
        supported_intents=["policy_query"],
        required_entities=[],
        output_schema="SubAgentResult",
        private_tools=["query_policy_status"],
        public_tools_allowed=True,
        skills=["policy_query_agent.default"],
        rag_namespaces=[],
        enabled=True,
        version="1",
    )
    registry.get_definition("calculator_tool").enabled = False

    schemas = registry.list_tools_for_agent(card)
    names = {schema["function"]["name"] for schema in schemas}

    assert {"query_policy_status", "rag_search_tool", "get_knowledge"}.issubset(names)
    assert "query_policy_info" not in names
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
    policy_result = await executor.execute(
        agent_name="policy_query_agent",
        agent_card=_card("policy_query_agent"),
        tool_name="query_policy_status",
        arguments={},
    )
    write_result = await executor.execute(
        agent_name="policy_query_agent",
        agent_card=_card("policy_query_agent"),
        tool_name="update_policy_status",
        arguments={"policy_no": "9201344266"},
    )

    assert public_result.success is False
    assert public_result.error == "missing_required_argument:query"
    assert policy_result.success is False
    assert policy_result.error == "missing_required_argument:policy_no"
    assert write_result.success is False
    assert write_result.error == "missing_required_argument:status"
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
