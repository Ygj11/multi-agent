"""IntentRecognitionNode tests."""

from app.query.intent_recognition_node import IntentRecognitionNode


async def test_e102_is_troubleshooting_with_entities():
    node = IntentRecognitionNode()
    result = await node.recognize(
        original_query="REQ_001 为什么返回 E102？",
        rewritten_query="排查 requestId=REQ_001 的健康险个险接口 E102 错误原因",
    )

    assert result.intent == "troubleshooting"
    assert result.entities["request_id"] == "REQ_001"
    assert result.entities["error_code"] == "E102"
    assert result.sub_intent is None
    assert result.target_subagent is None
    assert "required_tools" not in result.model_dump()


async def test_follow_up_with_summary_is_troubleshooting():
    node = IntentRecognitionNode()
    result = await node.recognize(
        original_query="那这个一般是谁的问题？",
        rewritten_query="继续排查上一轮 requestId 的 E102 签名校验失败问题，并判断问题归属",
        short_summary="上一轮讨论 requestId=REQ_001 的 submitProposal E102 问题。",
    )
    assert result.intent == "troubleshooting"


async def test_endo_completion_aftercare_is_troubleshooting():
    node = IntentRecognitionNode()
    result = await node.recognize(
        original_query="保全任务完成，受理号930010412672222，保单9200100000458846没有更新？",
        rewritten_query="保全任务完成，受理号930010412672222，保单9200100000458846没有更新？",
    )

    assert result.intent == "troubleshooting"
    assert result.sub_intent == "endo_completion_aftercare"
    assert result.entities["apply_seq"] == "930010412672222"
    assert result.entities["policy_no"] == "9200100000458846"


async def test_removed_product_rule_intent_is_unknown():
    node = IntentRecognitionNode()
    result = await node.recognize(original_query="等待期责任条款是什么？", rewritten_query="等待期责任条款是什么？")
    assert result.intent == "unknown"
