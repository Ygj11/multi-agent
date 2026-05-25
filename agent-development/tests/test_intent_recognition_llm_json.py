import json

from app.llm.schemas import LLMResponse
from app.query.intent_recognition_node import IntentRecognitionNode


class JsonLLM:
    def __init__(self, payload):
        self.payload = payload

    async def chat(self, *args, **kwargs):
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
                "entities": {"policy_no": "9201344266"},
                "need_clarification": False,
                "reason": "json",
            }
        )
    )

    result = await node.recognize("退保失败，保单号9201344266", "退保失败，保单号9201344266")

    assert result.intent == "troubleshooting"
    assert result.sub_intent == "refund_failure"
    assert result.entities["policy_no"] == "9201344266"
    assert "required_tools" not in result.model_dump()


async def test_intent_invalid_json_fallback_business_cases():
    node = IntentRecognitionNode(llm_provider=InvalidJsonLLM())

    cases = [
        ("REQ_001 为什么返回 E102？", "troubleshooting", "signature_error"),
        ("退保失败，保单 P2021344266", "troubleshooting", "refund_failure"),
        ("理赔 CLM_001 进度", "claim_query", "claim_progress"),
        ("保单 P2021344266 状态", "policy_query", "policy_status"),
        ("请做合规审查，手机号13800138000", "compliance_review", "privacy_review"),
        ("请解析 submitProposal 接口文档", "document_parse", "api_doc_parse"),
    ]
    for query, intent, sub_intent in cases:
        result = await node.recognize(query, query)
        assert result.intent == intent
        assert result.sub_intent == sub_intent
        assert isinstance(result.entities, dict)
