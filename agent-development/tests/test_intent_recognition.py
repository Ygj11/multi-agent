"""IntentRecognitionNode 验收测试。"""

from app.query.intent_recognition_node import IntentRecognitionNode


async def test_e102_is_troubleshooting():
    """E102/requestId 应识别为 troubleshooting 并指向问题排查子 Agent。"""
    node = IntentRecognitionNode()
    result = await node.recognize(
        original_query="REQ_001 为什么返回 E102？",
        rewritten_query="排查 requestId=REQ_001 的健康险个险接口 E102 错误原因",
    )
    assert result.intent == "troubleshooting"
    assert result.target_subagent == "troubleshooting_agent"
    assert "query_internal_log" in result.required_tools


async def test_follow_up_with_summary_is_troubleshooting():
    """追问在存在 E102 摘要时仍应识别为 troubleshooting。"""
    node = IntentRecognitionNode()
    result = await node.recognize(
        original_query="那这个一般是谁的问题？",
        rewritten_query="继续排查上一轮 requestId 的 E102 签名校验失败问题，并判断问题归属",
        short_summary="上一轮讨论 requestId=REQ_001 的 submitProposal E102 问题。",
    )
    assert result.intent == "troubleshooting"


async def test_product_rule_intent():
    """产品条款关键词应识别为 product_rule_qa。"""
    node = IntentRecognitionNode()
    result = await node.recognize(original_query="等待期责任条款是什么？", rewritten_query="等待期责任条款是什么？")
    assert result.intent == "product_rule_qa"
