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
    llm = SpyRouterLLM({"selected_agent": "claim_agent", "confidence": 0.9})
    node = AgentSelectionNode(AgentCardLoader(__import__("pathlib").Path("app/agents/cards")), llm_provider=llm)

    result = await node.select(
        intent="claim_query",
        sub_intent="claim_progress",
        intent_confidence=0.95,
        entities={"claim_no": "CLM_001"},
        query="理赔 CLM_001 进度 claim progress claim_case_query claim_progress_query",
    )

    assert result.selected_agent == "claim_agent"
    assert result.selection_method == "rule"
    assert llm.calls == 0


async def test_close_rule_scores_call_llm_router():
    llm = SpyRouterLLM({"selected_agent": "policy_query_agent", "confidence": 0.81, "reason": "policy"})
    node = AgentSelectionNode(AgentCardLoader(__import__("pathlib").Path("app/agents/cards")), llm_provider=llm)

    result = await node.select(
        intent="unknown",
        intent_confidence=0.4,
        entities={"policy_no": "P2021344266"},
        query="帮我看一下这个状态",
    )

    assert llm.calls == 1
    assert result.selected_agent == "policy_query_agent"
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
    llm = SpyRouterLLM({"selected_agent": "policy_query_agent", "confidence": 0.2, "clarification_question": "请明确业务"})
    node = AgentSelectionNode(AgentCardLoader(__import__("pathlib").Path("app/agents/cards")), llm_provider=llm)

    result = await node.select(intent="unknown", intent_confidence=0.4, entities={"policy_no": "P2021344266"}, query="状态")

    assert result.need_clarification is True


def test_optional_entities_score_and_required_missing_recorded():
    loader = AgentCardLoader(__import__("pathlib").Path("app/agents/cards"))

    candidates = loader.match_candidates(intent="policy_query", entities={"policy_no": "P2021344266"}, query="policy status")
    assert candidates[0].agent_name == "policy_query_agent"
    assert "policy_no" in candidates[0].matched_entities

    claim_candidates = loader.match_candidates(intent="claim_query", entities={}, query="claim progress")
    claim = next(item for item in claim_candidates if item.agent_name == "claim_agent")
    assert claim.missing_entities == []
