import pytest

from app.mcp.schemas import MCPToolCapability
from app.schemas.agent_card import AgentCard
from app.storage.sqlite import SQLiteDatabase
from app.tools.tool_execution_log_store import ToolExecutionLogStore
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from tests.fakes.mcp import FakeMCPClientManager


def _cap():
    return MCPToolCapability(
        server_name="workflow",
        original_tool_name="query_refund_task",
        registered_tool_name="mcp.workflow.query_refund_task",
        description="query refund",
        input_schema={"type": "object", "properties": {"policy_no": {"type": "string"}}},
    )


def _card(allowed=True):
    return AgentCard(
        agent_name="troubleshooting_agent",
        display_name="Troubleshooting",
        description="test",
        capabilities=["test"],
        supported_intents=["troubleshooting"],
        required_entities=[],
        output_schema="SubAgentResult",
        private_tools=[],
        public_tools_allowed=False,
        mcp_tools=["mcp.workflow.query_refund_task"] if allowed else [],
        mcp_tool_scopes=[],
        skills=["troubleshooting_agent.signature_error"],
        rag_namespaces=[],
        enabled=True,
        version="1",
    )


def _executor(tmp_path, mode="success"):
    registry = ToolRegistry()
    registry.register_mcp_tools([_cap()])
    store = ToolExecutionLogStore(SQLiteDatabase(tmp_path / f"{mode}.sqlite3"))
    manager = FakeMCPClientManager(mode=mode)
    return ToolExecutor(registry, store, manager), store, manager


@pytest.mark.asyncio
async def test_agent_can_execute_authorized_mcp_tool_and_logs(tmp_path):
    executor, store, manager = _executor(tmp_path)

    result = await executor.execute(
        agent_name="troubleshooting_agent",
        agent_card=_card(),
        tool_name="mcp.workflow.query_refund_task",
        arguments={"policy_no": "9201344266"},
        session_key="s-mcp",
    )

    logs = await store.list_by_session("s-mcp")
    assert result.success is True
    assert manager.calls == [("mcp.workflow.query_refund_task", {"policy_no": "9201344266"})]
    assert logs[0]["source"] == "mcp"
    assert logs[0]["server_name"] == "workflow"
    assert logs[0]["original_tool_name"] == "query_refund_task"


@pytest.mark.asyncio
async def test_unauthorized_mcp_tool_is_rejected_and_logged(tmp_path):
    executor, store, _ = _executor(tmp_path)

    result = await executor.execute(
        agent_name="troubleshooting_agent",
        agent_card=_card(allowed=False),
        tool_name="mcp.workflow.query_refund_task",
        arguments={},
        session_key="s-mcp",
    )

    logs = await store.list_by_session("s-mcp")
    assert result.success is False
    assert result.error == "tool_not_available_for_agent"
    assert logs[0]["success"] is False


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    [
        ("unavailable", "mcp_server_unavailable"),
        ("timeout", "mcp_tool_timeout"),
        ("error", "mcp_tool_error"),
    ],
)
@pytest.mark.asyncio
async def test_mcp_error_modes_are_normalized_and_logged(tmp_path, mode, expected_error):
    executor, store, _ = _executor(tmp_path, mode=mode)

    result = await executor.execute(
        agent_name="troubleshooting_agent",
        agent_card=_card(),
        tool_name="mcp.workflow.query_refund_task",
        arguments={},
        session_key="s-mcp",
    )

    logs = await store.list_by_session("s-mcp")
    assert result.success is False
    assert result.error == expected_error
    assert logs[0]["error"] == expected_error
