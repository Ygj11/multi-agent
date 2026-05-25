from app.llm.schemas import LLMResponse
from app.query.query_rewrite_node import QueryRewriteNode


class InvalidJsonLLM:
    async def chat(self, *args, **kwargs):
        return LLMResponse(content="not json", finish_reason="stop", model="fake")


async def test_follow_up_inherits_unique_policy_no():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite("继续查一下状态", short_summary="上一轮保单号 P2021344266。")

    assert result.inherited_entities["policy_no"] == "P2021344266"
    assert result.need_clarification is False
    assert "policy_no=P2021344266" in result.rewritten_query


async def test_multiple_policy_no_candidates_need_clarification():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite("继续查一下", short_summary="有两个保单号 P2021344266 和 P2021344267。")

    assert result.need_clarification is True
    assert "多个 policy_no" in result.clarification_question


async def test_claim_no_follow_up_inherits():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite("继续看进度", short_summary="上一轮理赔号 CLM_001。")

    assert result.inherited_entities["claim_no"] == "CLM_001"


async def test_unresolvable_follow_up_needs_clarification():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite("继续看一下")

    assert result.need_clarification is True


async def test_req_001_e102_still_rewrites_with_entity_extractor_fallback():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite("REQ_001 为什么返回 E102？")

    assert result.rewritten_query == "排查 requestId=REQ_001 的健康险个险接口 E102 错误原因"
    assert result.entities["request_id"] == "REQ_001"
    assert result.entities["error_code"] == "E102"
