from pathlib import Path

from app.agents.card_loader import AgentCardLoader
from app.tools.agent_tools import register_agent_private_tools
from app.tools.public_tools import register_public_tools
from app.tools.registry import ToolRegistry
from tests.fakes.fake_knowledge_service import FakeKnowledgeService


def _registry():
    registry = ToolRegistry()
    register_public_tools(registry, FakeKnowledgeService())
    register_agent_private_tools(registry)
    return registry


def _card(name: str):
    return AgentCardLoader(Path("app/agents/cards")).get_agent_card(name)


def test_troubleshooting_sees_own_private_and_public_tools():
    names = {schema["function"]["name"] for schema in _registry().list_tools_for_agent(_card("troubleshooting_agent"))}

    assert "query_internal_log" in names
    assert "mcp.workflow.query_refund_task" not in names
    assert "rag_search_tool" in names
    assert "pos_query_available_items" not in names


def test_pos_query_does_not_see_troubleshooting_private_tools():
    names = {schema["function"]["name"] for schema in _registry().list_tools_for_agent(_card("pos_query_agent"))}

    assert "pos_query_available_items" in names
    assert "query_internal_log" not in names


def test_troubleshooting_does_not_see_pos_query_private_tools():
    names = {schema["function"]["name"] for schema in _registry().list_tools_for_agent(_card("troubleshooting_agent"))}

    assert "query_internal_log" in names
    assert "pos_query_available_items" not in names
