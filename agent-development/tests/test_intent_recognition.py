"""IntentRecognitionNode tests."""

from app.query.intent_recognition_node import IntentRecognitionNode
from app.schemas.entities import ConversationWindow, EntityBag
from app.schemas.enums.query import RewriteType


def _window(entities: dict | None = None) -> dict:
    bag = EntityBag.from_compact_dict(entities or {}, source="current_query", confidence=0.9)
    return ConversationWindow(session_key="test-session", entity_bag=bag).model_dump()


async def test_e102_is_troubleshooting_with_entities():
    node = IntentRecognitionNode()
    result = await node.recognize(
        original_query="REQ_001 为什么返回 E102？",
        rewritten_query="排查 requestId=REQ_001 的健康险个险接口 E102 错误原因",
        entities={"request_id": "REQ_001", "error_code": "E102"},
        rewrite_type=RewriteType.DIRECT,
        conversation_window=_window({"request_id": "REQ_001", "error_code": "E102"}),
    )

    assert result.intent == "troubleshooting"
    assert result.sub_intent is None
    assert "entities" not in result.model_dump()
    assert "missing_required_entities" not in result.model_dump()
    assert "is_follow_up" not in result.model_dump()
    assert "target_subagent" not in result.model_dump()
    assert "required_tools" not in result.model_dump()


async def test_follow_up_with_summary_is_troubleshooting():
    node = IntentRecognitionNode()
    result = await node.recognize(
        original_query="那这个一般是谁的问题？",
        rewritten_query="继续排查上一轮 requestId 的 E102 签名校验失败问题，并判断问题归属",
        entities={"request_id": "REQ_001", "error_code": "E102"},
        rewrite_type=RewriteType.CONTEXTUAL_FOLLOW_UP,
        conversation_window=_window({"request_id": "REQ_001", "error_code": "E102"}),
    )
    assert result.intent == "troubleshooting"


async def test_endo_completion_aftercare_is_troubleshooting():
    node = IntentRecognitionNode()
    result = await node.recognize(
        original_query="保全任务完成，受理号930010412672222，保单9200100000458846没有更新？",
        rewritten_query="保全任务完成，受理号930010412672222，保单9200100000458846没有更新？",
        entities={"apply_seq": "930010412672222", "policy_no": "9200100000458846"},
        rewrite_type=RewriteType.NEW_REQUEST,
        conversation_window=_window({"apply_seq": "930010412672222", "policy_no": "9200100000458846"}),
    )

    assert result.intent == "troubleshooting"
    assert result.sub_intent == "endo_completion_aftercare"
    assert "entities" not in result.model_dump()


async def test_removed_product_rule_intent_is_unknown():
    node = IntentRecognitionNode()
    result = await node.recognize(
        original_query="等待期责任条款是什么？",
        rewritten_query="等待期责任条款是什么？",
        entities={},
        rewrite_type=RewriteType.DIRECT,
        conversation_window=_window(),
    )
    assert result.intent == "unknown"
