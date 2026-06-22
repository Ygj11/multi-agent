from pathlib import Path

from app.agents.card_loader import AgentCardLoader
from app.agents.routing_policy import AgentRoutingPolicy
from app.agents.selection import AgentSelectionNode


def test_agent_routing_policy_loads_yaml():
    policy = AgentRoutingPolicy.load()

    assert policy.version == "1.0.0"
    assert policy.weight("intent_match") == 6.0
    assert policy.threshold("top_k", 0) == 3.0
    assert "e102" in policy.keyword_tokens


def test_agent_card_loader_uses_injected_routing_weights():
    policy = AgentRoutingPolicy(
        version="test-policy",
        weights={
            "intent_match": 100.0,
            "intent_capability_keyword": 0.0,
            "sub_intent_match": 0.0,
            "required_entity_present": 0.0,
            "required_entity_missing": 0.0,
            "no_required_entities": 0.0,
            "optional_entity_present": 0.0,
            "capability_keyword": 0.0,
            "query_keyword": 0.0,
            "enabled": 0.0,
        },
        thresholds={},
        keyword_tokens=(),
        clarification_question="custom clarify",
    )
    loader = AgentCardLoader(Path("app/agents/cards"), routing_policy=policy)

    candidates = loader.match_candidates(intent="pos_query", sub_intent=None, entities={}, query="")

    assert candidates[0].agent_name == "pos_query_agent"
    assert candidates[0].score == 100.0


async def test_agent_selection_records_routing_policy_trace():
    loader = AgentCardLoader(Path("app/agents/cards"))
    node = AgentSelectionNode(loader, llm_provider=None)

    result = await node.select(
        intent="pos_query",
        sub_intent="pos_available_items",
        intent_confidence=0.9,
        entities={"policy_no": "9200100000458846"},
        query="查询保单可以做哪些保全项",
    )

    assert result.selected_agent == "pos_query_agent"
    assert result.decision_trace["policy_name"] == "agent_routing_policy"
    assert result.decision_trace["policy_version"] == "1.0.0"
