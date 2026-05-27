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


def test_registry_registers_public_and_private_tools():
    registry = _registry()

    assert "rag_search_tool" in registry.list_public_tools()
    assert "query_internal_log" in registry.list_private_tools("troubleshooting_agent")


def test_list_tools_for_agent_returns_only_visible_tool_schemas():
    registry = _registry()
    card = _card("troubleshooting_agent")
    schemas = registry.list_tools_for_agent(card)
    names = {schema["function"]["name"] for schema in schemas}

    assert "query_internal_log" in names
    assert "rag_search_tool" in names
    assert "query_claim_case" not in names
    assert all(schema["type"] == "function" for schema in schemas)


def test_public_tools_hidden_when_card_disables_public_tools():
    registry = _registry()
    card = _card("compliance_agent")
    names = {schema["function"]["name"] for schema in registry.list_tools_for_agent(card)}

    assert "rag_search_tool" not in names
    assert "query_claim_case" not in names
