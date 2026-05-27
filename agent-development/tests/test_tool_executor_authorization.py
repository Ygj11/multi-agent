from pathlib import Path

import pytest

from app.agents.card_loader import AgentCardLoader
from app.storage.sqlite import SQLiteDatabase
from app.tools.agent_tools import register_agent_private_tools
from app.tools.tool_execution_log_store import ToolExecutionLogStore
from app.tools.executor import ToolExecutor
from app.tools.public_tools import register_public_tools
from app.tools.registry import ToolRegistry
from tests.fakes.fake_knowledge_service import FakeKnowledgeService


def _executor(tmp_path: Path):
    registry = ToolRegistry()
    register_public_tools(registry, FakeKnowledgeService())
    register_agent_private_tools(registry)
    store = ToolExecutionLogStore(SQLiteDatabase(tmp_path / "tools.sqlite3"))
    return ToolExecutor(registry, store), store


def _card(name: str):
    return AgentCardLoader(Path("app/agents/cards")).get_agent_card(name)


@pytest.mark.asyncio
async def test_agent_can_call_own_private_tool_and_logs_success(tmp_path):
    executor, store = _executor(tmp_path)
    card = _card("troubleshooting_agent")

    result = await executor.execute(
        agent_name="troubleshooting_agent",
        agent_card=card,
        tool_name="query_internal_log",
        arguments={"request_id": "REQ_001"},
        session_key="s-tools",
    )

    logs = await store.list_by_session("s-tools")
    assert result.success is True
    assert logs[0]["tool_name"] == "query_internal_log"
    assert logs[0]["success"] is True


@pytest.mark.asyncio
async def test_public_tools_disallowed_when_card_disables_public_tools_and_logs_failure(tmp_path):
    executor, store = _executor(tmp_path)
    card = _card("compliance_agent")

    result = await executor.execute(
        agent_name="compliance_agent",
        agent_card=card,
        tool_name="get_knowledge",
        arguments={"query": "E102"},
        session_key="s-tools",
    )

    logs = await store.list_by_session("s-tools")
    assert result.success is False
    assert result.error == "tool_not_available_for_agent"
    assert logs[0]["success"] is False
    assert logs[0]["error"] == "tool_not_available_for_agent"


@pytest.mark.asyncio
async def test_agents_cannot_call_other_agent_private_tools(tmp_path):
    executor, store = _executor(tmp_path)
    card = _card("claim_agent")

    result = await executor.execute(
        agent_name="claim_agent",
        agent_card=card,
        tool_name="query_policy_info",
        arguments={"policy_no": "P001"},
        session_key="s-tools",
    )

    logs = await store.list_by_session("s-tools")
    assert result.success is False
    assert result.error == "tool_not_available_for_agent"
    assert logs[0]["tool_name"] == "query_policy_info"
    assert logs[0]["success"] is False


@pytest.mark.asyncio
async def test_agent_can_call_public_tool_when_card_allows_public_tools(tmp_path):
    executor, store = _executor(tmp_path)
    card = _card("troubleshooting_agent")

    result = await executor.execute(
        agent_name="troubleshooting_agent",
        agent_card=card,
        tool_name="rag_search_tool",
        arguments={"query": "E102", "top_k": 1},
        session_key="s-tools-public",
    )

    logs = await store.list_by_session("s-tools-public")
    assert result.success is True
    assert logs[0]["tool_name"] == "rag_search_tool"
    assert logs[0]["success"] is True
