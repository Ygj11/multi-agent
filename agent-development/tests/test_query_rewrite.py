"""QueryRewriteNode 验收测试。"""

from app.query.query_rewrite_node import QueryRewriteNode


async def test_rewrite_req_001_e102():
    """REQ_001 + E102 应改写为标准排查查询。"""
    node = QueryRewriteNode()
    result = await node.rewrite("REQ_001 为什么返回 E102？")
    assert result.rewritten_query == "排查 requestId=REQ_001 的健康险个险接口 E102 错误原因"


async def test_rewrite_req_002_e102():
    """REQ_002 + E102 应改写为标准排查查询。"""
    node = QueryRewriteNode()
    result = await node.rewrite("帮我看下 REQ_002 的 E102")
    assert result.rewritten_query == "排查 requestId=REQ_002 的健康险个险接口 E102 错误原因"


async def test_rewrite_follow_up_uses_context():
    """多轮追问应从 short_summary 中补全上一轮 E102 上下文。"""
    node = QueryRewriteNode()
    result = await node.rewrite(
        "那这个一般是谁的问题？",
        short_summary="上一轮讨论 requestId=REQ_001 的 submitProposal E102 问题。",
    )
    assert result.rewritten_query == "继续排查上一轮 requestId=REQ_001 的 E102 签名校验失败问题，并判断问题归属"
    assert result.inherited_entities["request_id"] == "REQ_001"
