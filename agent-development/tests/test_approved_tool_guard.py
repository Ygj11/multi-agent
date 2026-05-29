from pathlib import Path

import pytest

from app.approval.store import SQLiteApprovalStore
from app.schemas.agent_card import AgentCard
from app.schemas.approval import ApprovalRequest
from app.storage.sqlite import SQLiteDatabase
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.tools.tool_execution_log_store import ToolExecutionLogStore


async def _write_tool(value: str = ""):
    return {"success": True, "value": value}


def _card() -> AgentCard:
    return AgentCard(
        agent_name="agent_a",
        display_name="Agent A",
        description="test",
        capabilities=["test"],
        supported_intents=["test"],
        required_entities=[],
        output_schema="SubAgentResult",
        private_tools=["write_tool"],
        public_tools_allowed=False,
        skills=["agent_a.default"],
        rag_namespaces=[],
        enabled=True,
        version="1",
    )


async def _executor(tmp_path: Path):
    registry = ToolRegistry()
    registry.register_private(agent_name="agent_a", name="write_tool", tool=_write_tool, is_write=True)
    store = SQLiteApprovalStore(SQLiteDatabase(tmp_path / "approval_guard.sqlite3"))
    return ToolExecutor(registry=registry, approval_store=store), store


@pytest.mark.asyncio
async def test_execute_approved_tool_requires_store(tmp_path):
    registry = ToolRegistry()
    registry.register_private(agent_name="agent_a", name="write_tool", tool=_write_tool, is_write=True)
    executor = ToolExecutor(registry=registry)

    result = await executor.execute_approved_tool(
        approval_id="approval_missing",
        agent_name="agent_a",
        tool_name="write_tool",
        arguments={"value": "x"},
        session_key="s",
        request_id="r",
        trace_id=None,
        agent_card=_card(),
    )

    assert result.success is False
    assert result.error == "approval_store_not_configured"


@pytest.mark.asyncio
async def test_execute_approved_tool_validates_approval_id(tmp_path):
    executor, _store = await _executor(tmp_path)

    result = await executor.execute_approved_tool(
        approval_id="approval_missing",
        agent_name="agent_a",
        tool_name="write_tool",
        arguments={"value": "x"},
        session_key="s",
        request_id="r",
        trace_id=None,
        agent_card=_card(),
    )

    assert result.success is False
    assert result.error == "approval_not_found"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "agent_name", "tool_name", "arguments", "expected"),
    [
        ("pending", "agent_a", "write_tool", {"value": "x"}, "approval_not_approved"),
        ("approved", "other_agent", "write_tool", {"value": "x"}, "approval_agent_mismatch"),
        ("approved", "agent_a", "other_tool", {"value": "x"}, "approval_tool_mismatch"),
        ("approved", "agent_a", "write_tool", {"value": "y"}, "approval_arguments_mismatch"),
    ],
)
async def test_execute_approved_tool_rejects_mismatches(tmp_path, status, agent_name, tool_name, arguments, expected):
    executor, store = await _executor(tmp_path)
    await store.create(
        ApprovalRequest(
            approval_id="approval_1",
            session_key="s",
            request_id="r",
            agent_name="agent_a",
            tool_name="write_tool",
            arguments={"value": "x"},
            reason="test",
            status=status,
        )
    )

    result = await executor.execute_approved_tool(
        approval_id="approval_1",
        agent_name=agent_name,
        tool_name=tool_name,
        arguments=arguments,
        session_key="s",
        request_id="r",
        trace_id=None,
        agent_card=_card(),
    )

    assert result.success is False
    assert result.error == expected


@pytest.mark.asyncio
async def test_execute_approved_tool_runs_when_approval_matches(tmp_path):
    executor, store = await _executor(tmp_path)
    await store.create(
        ApprovalRequest(
            approval_id="approval_1",
            session_key="s",
            request_id="r",
            agent_name="agent_a",
            tool_name="write_tool",
            arguments={"value": "x"},
            reason="test",
            status="approved",
        )
    )

    result = await executor.execute_approved_tool(
        approval_id="approval_1",
        agent_name="agent_a",
        tool_name="write_tool",
        arguments={"value": "x"},
        session_key="s",
        request_id="r",
        trace_id=None,
        agent_card=_card(),
    )

    assert result.success is True
    assert result.approval_id == "approval_1"
    assert result.result == {"success": True, "value": "x"}


@pytest.mark.asyncio
async def test_execute_approved_tool_replays_successful_approval_idempotently(tmp_path):
    calls: list[str] = []

    async def counted_write_tool(value: str = ""):
        calls.append(value)
        return {"success": True, "value": value}

    registry = ToolRegistry()
    registry.register_private(agent_name="agent_a", name="write_tool", tool=counted_write_tool, is_write=True)
    db = SQLiteDatabase(tmp_path / "approval_idempotency.sqlite3")
    store = SQLiteApprovalStore(db)
    log_store = ToolExecutionLogStore(db)
    executor = ToolExecutor(registry=registry, log_store=log_store, approval_store=store)
    await store.create(
        ApprovalRequest(
            approval_id="approval_1",
            session_key="s",
            request_id="r",
            agent_name="agent_a",
            tool_name="write_tool",
            arguments={"value": "x"},
            reason="test",
            status="approved",
        )
    )

    first = await executor.execute_approved_tool(
        approval_id="approval_1",
        agent_name="agent_a",
        tool_name="write_tool",
        arguments={"value": "x"},
        session_key="s",
        request_id="r",
        trace_id=None,
        agent_card=_card(),
    )
    second = await executor.execute_approved_tool(
        approval_id="approval_1",
        agent_name="agent_a",
        tool_name="write_tool",
        arguments={"value": "x"},
        session_key="s",
        request_id="r",
        trace_id=None,
        agent_card=_card(),
    )

    assert first.success is True
    assert second.success is True
    assert second.result["reason"] == "idempotent_replay"
    assert second.result["previous_result"] == {"success": True, "value": "x"}
    assert calls == ["x"]
