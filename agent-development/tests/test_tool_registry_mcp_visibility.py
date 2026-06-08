from app.schemas.agent_card import AgentCard
from app.mcp.schemas import MCPToolCapability
from app.tools.registry import ToolRegistry


async def _local_tool(**kwargs):
    return {"ok": True}


def _card(**overrides):
    data = dict(
        agent_name="agent_a",
        display_name="Agent A",
        description="test",
        capabilities=["test"],
        supported_intents=["test"],
        required_entities=[],
        output_schema="SubAgentResult",
        private_tools=["private_tool"],
        public_tools_allowed=True,
        mcp_tools=[],
        mcp_tool_scopes=[],
        skills=["agent_a.default"],
        rag_namespaces=[],
        enabled=True,
        version="1",
    )
    data.update(overrides)
    return AgentCard(**data)


def _cap(name: str, server="workflow"):
    return MCPToolCapability(
        server_name=server,
        original_tool_name=name.split(".")[-1],
        registered_tool_name=name,
        description=f"{name} desc",
        input_schema={"type": "object", "properties": {"policy_no": {"type": "string"}}},
    )


def _registry():
    registry = ToolRegistry()
    registry.register_private(agent_name="agent_a", name="private_tool", tool=_local_tool)
    registry.register_public_tool("public_tool", _local_tool)
    registry.register_mcp_tools(
        [
            _cap("mcp.workflow.query_refund_task"),
            _cap("mcp.workflow.query_node"),
            _cap("mcp.audit.query_audit_detail", server="audit"),
        ]
    )
    return registry


def test_register_mcp_tools_and_exact_visibility():
    registry = _registry()
    card = _card(mcp_tools=["mcp.workflow.query_refund_task"], mcp_tool_scopes=[])
    names = registry.list_tool_names_for_agent(card)

    assert "private_tool" in names
    assert "public_tool" in names
    assert "mcp.workflow.query_refund_task" in names
    assert "mcp.workflow.query_node" not in names
    assert "mcp.audit.query_audit_detail" not in names


def test_scope_visibility_does_not_return_all_mcp_tools():
    registry = _registry()
    card = _card(mcp_tools=[], mcp_tool_scopes=["mcp.workflow"])
    names = registry.list_tool_names_for_agent(card)

    assert "mcp.workflow.query_refund_task" in names
    assert "mcp.workflow.query_node" in names
    assert "mcp.audit.query_audit_detail" not in names


def test_public_disabled_keeps_private_and_mcp_but_hides_public():
    registry = _registry()
    card = _card(public_tools_allowed=False, mcp_tools=["mcp.workflow.query_refund_task"])
    names = registry.list_tool_names_for_agent(card)

    assert "private_tool" in names
    assert "public_tool" not in names
    assert "mcp.workflow.query_refund_task" in names


def test_mcp_schema_generation():
    schema = _registry().get_tool_schema("mcp.workflow.query_refund_task")

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "mcp.workflow.query_refund_task"
    assert schema["function"]["parameters"]["properties"]["policy_no"]["type"] == "string"
