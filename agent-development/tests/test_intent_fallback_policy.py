from app.query.intent_fallback_policy import IntentFallbackPolicy
from app.query.intent_recognition_node import IntentRecognitionNode
from app.schemas.entities import ConversationWindow, EntityBag
from app.schemas.enums.query import RewriteType


def _window(entities: dict | None = None) -> dict:
    bag = EntityBag.from_compact_dict(entities or {}, source="current_query", confidence=0.9)
    return ConversationWindow(session_key="test-session", entity_bag=bag).model_dump()


def test_intent_fallback_policy_classifies_from_yaml():
    policy = IntentFallbackPolicy.load()

    pos = policy.classify(text="查询保单可以做哪些保全项", entities={})
    troubleshooting = policy.classify(text="保全任务完成但是保单没有更新", entities={})
    entity_hint = policy.classify(text="帮我看一下", entities={"request_id": "REQ_001"})
    unknown = policy.classify(text="你好", entities={})

    assert pos.intent == "pos_query"
    assert pos.sub_intent == "pos_available_items"
    assert troubleshooting.intent == "troubleshooting"
    assert troubleshooting.sub_intent == "endo_completion_aftercare"
    assert entity_hint.intent == "troubleshooting"
    assert unknown.intent == "unknown"
    assert "业务类型" in unknown.clarification_question


async def test_intent_recognition_rule_fallback_records_policy_trace():
    node = IntentRecognitionNode(llm_provider=None)

    result = await node.recognize(
        original_query="保全任务完成，保单9200100000458846没有更新？",
        rewritten_query="保全任务完成，保单9200100000458846没有更新？",
        entities={"policy_no": "9200100000458846"},
        rewrite_type=RewriteType.NEW_REQUEST,
        conversation_window=_window({"policy_no": "9200100000458846"}),
    )

    assert result.intent == "troubleshooting"
    assert result.sub_intent == "endo_completion_aftercare"
    assert result.decision_trace["policy_name"] == "intent_fallback_policy"
    assert result.decision_trace["policy_version"] == "1.0.0"
    assert "保全任务完成" in result.decision_trace["matched_keywords"]
