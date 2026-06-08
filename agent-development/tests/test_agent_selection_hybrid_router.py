import json

from app.agents.card_loader import AgentCardLoader
from app.agents.selection import AgentSelectionNode
from app.llm.schemas import LLMResponse


class SpyRouterLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def chat(self, *args, **kwargs):
        self.calls += 1
        content = self.payload if isinstance(self.payload, str) else json.dumps(self.payload, ensure_ascii=False)
        return LLMResponse(content=content, finish_reason="stop", model="fake")


async def test_rule_high_confidence_does_not_call_llm_router():
    llm = SpyRouterLLM({"selected_agent": "troubleshooting_agent", "confidence": 0.9})
    node = AgentSelectionNode(AgentCardLoader(__import__("pathlib").Path("app/agents/cards")), llm_provider=llm)

    result = await node.select(
        intent="pos_query",
        sub_intent="pos_available_items",
        intent_confidence=0.95,
        entities={"policy_no": "9201344266", "customer_no": "C001"},
        query="查询保单 9201344266 可以做哪些保全项 保全实时查询 可做保全项查询",
    )

    assert result.selected_agent == "pos_query_agent"
    assert result.selection_method == "rule"
    assert llm.calls == 0


async def test_close_rule_scores_call_llm_router():
    llm = SpyRouterLLM({"selected_agent": "pos_query_agent", "confidence": 0.81, "reason": "pos"})
    node = AgentSelectionNode(AgentCardLoader(__import__("pathlib").Path("app/agents/cards")), llm_provider=llm)

    result = await node.select(
        intent="unknown",
        intent_confidence=0.4,
        entities={"policy_no": "P2021344266"},
        query="帮我看一下这个保单状态",
    )

    assert llm.calls == 1
    assert result.selected_agent == "pos_query_agent"
    assert result.selection_method == "llm_router"


async def test_llm_illegal_agent_falls_back_to_rule_top1():
    llm = SpyRouterLLM({"selected_agent": "not_allowed_agent", "confidence": 0.9})
    node = AgentSelectionNode(AgentCardLoader(__import__("pathlib").Path("app/agents/cards")), llm_provider=llm)

    result = await node.select(intent="unknown", intent_confidence=0.4, entities={"policy_no": "P2021344266"}, query="状态")

    assert result.selection_method == "fallback"
    assert result.selected_agent != "not_allowed_agent"


async def test_llm_invalid_json_falls_back():
    llm = SpyRouterLLM("not json")
    node = AgentSelectionNode(AgentCardLoader(__import__("pathlib").Path("app/agents/cards")), llm_provider=llm)

    result = await node.select(intent="unknown", intent_confidence=0.4, entities={"policy_no": "P2021344266"}, query="状态")

    assert result.selection_method == "fallback"


async def test_llm_low_confidence_requests_clarification():
    llm = SpyRouterLLM({"selected_agent": "pos_query_agent", "confidence": 0.2, "clarification_question": "请明确业务"})
    node = AgentSelectionNode(AgentCardLoader(__import__("pathlib").Path("app/agents/cards")), llm_provider=llm)

    result = await node.select(intent="unknown", intent_confidence=0.4, entities={"policy_no": "P2021344266"}, query="状态")

    assert result.need_clarification is True


def test_optional_entities_score_and_required_missing_recorded():
    loader = AgentCardLoader(__import__("pathlib").Path("app/agents/cards"))

    candidates = loader.match_candidates(intent="pos_query", entities={"policy_no": "P2021344266"}, query="保全实时查询")
    assert candidates[0].agent_name == "pos_query_agent"
    assert "policy_no" in candidates[0].matched_entities

    troubleshooting_candidates = loader.match_candidates(intent="troubleshooting", entities={}, query="E102")
    troubleshooting = next(item for item in troubleshooting_candidates if item.agent_name == "troubleshooting_agent")
    assert troubleshooting.missing_entities == []
