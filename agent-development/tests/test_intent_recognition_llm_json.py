import json

from app.llm.schemas import LLMResponse
from app.query.intent_recognition_node import IntentRecognitionNode


class JsonLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def chat(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return LLMResponse(content=json.dumps(self.payload, ensure_ascii=False), finish_reason="stop", model="fake")


class InvalidJsonLLM:
    async def chat(self, *args, **kwargs):
        return LLMResponse(content="not json", finish_reason="stop", model="fake")


async def test_intent_llm_json_primary_path():
    node = IntentRecognitionNode(
        llm_provider=JsonLLM(
            {
                "intent": "troubleshooting",
                "sub_intent": "refund_failure",
                "confidence": 0.91,
                "entities": {"policy_no": "9200100000458846"},
                "need_clarification": False,
                "reason": "json",
            }
        )
    )

    result = await node.recognize("退保失败，保单号9200100000458846", "退保失败，保单号9200100000458846")

    assert result.intent == "troubleshooting"
    assert result.sub_intent == "refund_failure"
    assert result.entities["policy_no"] == "9200100000458846"
    assert "required_tools" not in result.model_dump()


async def test_intent_invalid_json_fallback_business_cases():
    node = IntentRecognitionNode(llm_provider=InvalidJsonLLM())

    cases = [
        ("REQ_001 为什么返回 E102？", "troubleshooting", None),
        ("退保失败，保单 9200100000458846", "troubleshooting", "refund_failure"),
        ("查询保单 9200100000458846 可做保全项", "pos_query", "pos_available_items"),
    ]
    for query, intent, sub_intent in cases:
        result = await node.recognize(query, query)
        assert result.intent == intent
        assert result.sub_intent == sub_intent
        assert isinstance(result.entities, dict)


async def test_intent_llm_prompt_contains_dynamic_candidate_space():
    llm = JsonLLM(
        {
            "intent": "troubleshooting",
            "sub_intent": "refund_failure",
            "confidence": 0.91,
            "entities": {"policy_no": "9200100000458846"},
            "need_clarification": False,
            "reason": "json",
        }
    )
    node = IntentRecognitionNode(llm_provider=llm)

    result = await node.recognize(
        "refund failed for policy 9200100000458846",
        "refund failed for policy 9200100000458846",
        agent_card_summaries=[
                {
                    "agent_name": "troubleshooting_agent",
                    "description": "Troubleshooting.",
                    "supported_routes": {"troubleshooting": ["refund_failure"]},
                    "capabilities": ["refund_failure"],
                    "required_entities": [],
                    "optional_entities": ["policy_no"],
                    "examples": [{"query": "refund failed", "intent": "troubleshooting", "sub_intent": "refund_failure"}],
                }
            ],
        )

    assert result.intent == "troubleshooting"
    assert result.sub_intent == "refund_failure"
    prompt = llm.calls[0]["kwargs"]["messages"][1]["content"]
    assert "Intent taxonomy:" in prompt
    assert "Allowed intents: ['pos_query', 'troubleshooting']" in prompt
    assert "Candidate sub intents by intent:" in prompt


async def test_intent_llm_invalid_intent_falls_back_to_rules():
    node = IntentRecognitionNode(
        llm_provider=JsonLLM(
            {
                "intent": "made_up_intent",
                "sub_intent": "made_up_sub_intent",
                "confidence": 0.99,
                "entities": {},
                "need_clarification": False,
                "reason": "bad",
            }
        )
    )

    result = await node.recognize(
        "退保失败，保单 9200100000458846",
        "退保失败，保单 9200100000458846",
        agent_card_summaries=[
                {
                    "agent_name": "troubleshooting_agent",
                    "description": "Troubleshooting.",
                    "supported_routes": {"troubleshooting": ["refund_failure"]},
                    "capabilities": ["refund_failure"],
                    "required_entities": [],
                    "optional_entities": ["policy_no"],
                    "examples": [{"query": "退保失败", "intent": "troubleshooting", "sub_intent": "refund_failure"}],
                }
            ],
        )

    assert result.intent == "troubleshooting"
    assert result.sub_intent == "refund_failure"
    assert result.reason == "entity_aware_rule_fallback"


async def test_intent_llm_invalid_sub_intent_is_not_accepted():
    node = IntentRecognitionNode(
        llm_provider=JsonLLM(
            {
                "intent": "troubleshooting",
                "sub_intent": "not_in_candidates",
                "confidence": 0.9,
                "entities": {},
                "need_clarification": False,
            }
        )
    )

    result = await node.recognize(
        "Need troubleshooting help",
        "Need troubleshooting help",
        agent_card_summaries=[
                {
                    "agent_name": "troubleshooting_agent",
                    "description": "Troubleshooting.",
                    "supported_routes": {"troubleshooting": ["refund_failure"]},
                    "capabilities": ["refund_failure"],
                    "required_entities": [],
                    "optional_entities": [],
                "examples": [],
            }
        ],
    )

    assert result.intent == "troubleshooting"
    assert result.sub_intent is None


async def test_intent_llm_capability_is_not_accepted_as_sub_intent():
    node = IntentRecognitionNode(
        llm_provider=JsonLLM(
            {
                "intent": "troubleshooting",
                "sub_intent": "internal_log_analysis",
                "confidence": 0.9,
                "entities": {},
                "need_clarification": False,
            }
        )
    )

    result = await node.recognize(
        "Need log analysis",
        "Need log analysis",
        agent_card_summaries=[
            {
                "agent_name": "troubleshooting_agent",
                "description": "Troubleshooting.",
                "supported_routes": {"troubleshooting": ["refund_failure"]},
                "capabilities": ["internal_log_analysis"],
                "required_entities": [],
                "optional_entities": [],
                "examples": [],
            }
        ],
    )

    assert result.intent == "troubleshooting"
    assert result.sub_intent is None
