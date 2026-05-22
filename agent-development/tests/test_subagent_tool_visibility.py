from pathlib import Path

from app.agents.card_loader import AgentCardLoader
from app.knowledge.in_memory_service import InMemoryKnowledgeService
from app.tools.agent_tools import register_agent_private_tools
from app.tools.public_tools import register_public_tools
from app.tools.registry import ToolRegistry


def _registry():
    registry = ToolRegistry()
    register_public_tools(registry, InMemoryKnowledgeService())
    register_agent_private_tools(registry)
    return registry


def _card(name: str):
    return AgentCardLoader(Path("app/agents/cards")).get_agent_card(name)


def test_troubleshooting_sees_own_private_and_public_tools():
    names = {schema["function"]["name"] for schema in _registry().list_tools_for_agent(_card("troubleshooting_agent"))}

    assert "query_internal_log" in names
    assert "mcp.workflow.query_refund_task" not in names
    assert "rag_search_tool" in names
    assert "query_claim_case" not in names


def test_claim_does_not_see_troubleshooting_private_tools():
    names = {schema["function"]["name"] for schema in _registry().list_tools_for_agent(_card("claim_agent"))}

    assert "query_claim_case" in names
    assert "query_internal_log" not in names


def test_policy_query_does_not_see_claim_private_tools():
    names = {schema["function"]["name"] for schema in _registry().list_tools_for_agent(_card("policy_query_agent"))}

    assert "query_policy_info" in names
    assert "query_claim_case" not in names


def test_compliance_with_public_disabled_sees_no_public_tools():
    names = {schema["function"]["name"] for schema in _registry().list_tools_for_agent(_card("compliance_agent"))}

    assert "rag_search_tool" not in names
    assert "calculator_tool" not in names
