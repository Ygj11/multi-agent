import json

from app.llm.schemas import LLMResponse
from app.query.query_rewrite_node import QueryRewriteNode
from app.schemas.entities import EntityBag


class InvalidJsonLLM:
    async def chat(self, *args, **kwargs):
        return LLMResponse(content="not json", finish_reason="stop", model="fake")


class JsonLLM:
    def __init__(self, payload):
        self.payload = payload

    async def chat(self, *args, **kwargs):
        return LLMResponse(content=json.dumps(self.payload, ensure_ascii=False), finish_reason="stop", model="fake")


async def test_query_rewrite_llm_primary_path_records_prompt_manifest_trace():
    node = QueryRewriteNode(
        llm_provider=JsonLLM(
            {
                "is_follow_up": False,
                "rewritten_query": "保全任务完成，保单9200100000458846为什么没有更新？",
                "rewrite_type": "new_request",
                "entities": {"policy_no": "9200100000458846"},
                "inherited_entities": {},
                "missing_required_entities": [],
                "need_clarification": False,
                "clarification_question": None,
                "confidence": 0.92,
                "reason": "standalone request",
            }
        )
    )

    result = await node.rewrite("保全任务完成，保单9200100000458846没有更新？")

    assert result.rewrite_type == "new_request"
    assert result.entities["policy_no"] == "9200100000458846"
    assert result.decision_trace["prompt_scene"] == "query_rewrite"
    assert result.decision_trace["output_schema"] == "QueryRewriteLLMOutput"
    assert result.decision_trace["parse_status"] == "success"
    assert result.decision_trace["schema_status"] == "valid"


async def test_llm_entities_echo_does_not_overwrite_inherited_metadata():
    node = QueryRewriteNode(
        llm_provider=JsonLLM(
            {
                "is_follow_up": True,
                "rewritten_query": "继续处理保单 9200100000458846 的保全项 001028",
                "rewrite_type": "clarification_reply",
                "entities": {
                    "policy_no": "9200100000458846",
                    "endorseType": "001028",
                },
                "inherited_entities": {"policy_no": "9200100000458846"},
                "missing_required_entities": [],
                "need_clarification": False,
                "clarification_question": None,
                "confidence": 0.91,
                "reason": "clarification reply",
            }
        )
    )

    result = await node.rewrite("001028")

    assert result.entities == {
        "endorseType": "001028",
        "policy_no": "9200100000458846",
    }
    policy_mentions = EntityBag(**result.entity_bag).entities["policy_no"]
    assert len(policy_mentions) == 1
    assert policy_mentions[0].source == "recent_turn"
    assert policy_mentions[0].metadata["inherited"] is True
    assert result.inherited_entities == {"policy_no": "9200100000458846"}


async def test_llm_current_entities_cannot_override_inherited_type_without_current_anchor():
    node = QueryRewriteNode(
        llm_provider=JsonLLM(
            {
                "is_follow_up": True,
                "rewritten_query": "继续查看上一轮保单状态",
                "rewrite_type": "contextual_follow_up",
                "entities": {"policy_no": "9200100000458847"},
                "inherited_entities": {"policy_no": "9200100000458846"},
                "missing_required_entities": [],
                "need_clarification": False,
                "clarification_question": None,
                "confidence": 0.89,
                "reason": "follow up",
            }
        )
    )

    result = await node.rewrite("继续看一下")

    assert result.entities["policy_no"] == "9200100000458846"
    assert result.inherited_entities == {"policy_no": "9200100000458846"}


async def test_follow_up_inherits_unique_policy_no():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite("继续查一下状态", short_summary="上一轮保单号 9200100000458846。")

    assert result.inherited_entities["policy_no"] == "9200100000458846"
    assert result.need_clarification is False
    assert "policy_no=9200100000458846" in result.rewritten_query
    assert result.fallback_used is True
    assert result.fallback_source == "query_rewrite"
    assert result.fallback_reason == "llm_json_parse_failed"
    assert result.llm_status == "parse_failed"


async def test_multiple_policy_no_candidates_need_clarification():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite("继续查一下", short_summary="有两个保单号 9200100000458846 和 9200100000458847。")

    assert result.need_clarification is True
    assert "多个 policy_no" in result.clarification_question


async def test_current_turn_multiple_policy_numbers_are_preserved_for_batch_query():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())

    result = await node.rewrite("保单 9200100000458846 和 9200100000458847 的被保人是谁？")

    assert result.need_clarification is False
    assert result.rewrite_type == "new_request"
    assert result.entities["policy_no"] == ["9200100000458846", "9200100000458847"]
    assert EntityBag(**result.entity_bag).to_compact_dict()["policy_no"] == [
        "9200100000458846",
        "9200100000458847",
    ]


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


async def test_clarification_reply_inherits_previous_task_entities():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite(
        "001028",
        recent_messages=[
            {
                "role": "user",
                "content": "保单号 9200100000458846 保全任务完成但没更新",
                "metadata": {},
            },
            {
                "role": "assistant",
                "content": "执行保全任务完成后异常处理还缺少保全项 endorseType，请补充后我再继续处理。",
                "metadata": {
                    "need_clarification": True,
                    "original_query": "保单号 9200100000458846 保全任务完成但没更新",
                    "rewritten_query": "保单号 9200100000458846 保全任务完成但没更新",
                    "entities": {"policy_no": "9200100000458846"},
                    "missing_required_entities": ["endorseType"],
                },
            },
        ],
    )

    assert result.rewrite_type == "clarification_reply"
    assert result.entities["policy_no"] == "9200100000458846"
    assert result.entities["endorseType"] == "001028"
    assert result.inherited_entities == {"policy_no": "9200100000458846"}
    assert result.need_clarification is False
    assert "继续处理上一轮业务问题" in result.rewritten_query
    assert "已知实体" in result.rewritten_query
    assert "保全任务完成但没更新" in result.rewritten_query
    assert "用户补充：endorseType=001028" in result.rewritten_query


async def test_clarification_reply_rewrites_business_problem_with_apply_seq_supplement():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite(
        "930010412672222",
        recent_messages=[
            {
                "role": "assistant",
                "content": "还缺少受理号 apply_seq，请补充后我再继续处理。",
                "metadata": {
                    "need_clarification": True,
                    "rewritten_query": "保全任务完成后保单更新错误，保单 9200100000458846 没有更新",
                    "entities": {"policy_no": "9200100000458846"},
                    "missing_required_entities": ["apply_seq"],
                },
            }
        ],
    )

    assert result.rewrite_type == "clarification_reply"
    assert result.need_clarification is False
    assert result.entities["policy_no"] == "9200100000458846"
    assert result.entities["apply_seq"] == "930010412672222"
    assert "保单更新错误" in result.rewritten_query
    assert "policy_no=9200100000458846" in result.rewritten_query
    assert "apply_seq=930010412672222" in result.rewritten_query


async def test_clarification_reply_continues_when_required_entities_still_missing():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite(
        "001028",
        recent_messages=[
            {
                "role": "assistant",
                "content": "还缺少受理号 apply_seq 和保全项 endorseType。",
                "metadata": {
                    "need_clarification": True,
                    "entities": {"policy_no": "9200100000458846"},
                    "missing_required_entities": ["apply_seq", "endorseType"],
                },
            }
        ],
    )

    assert result.rewrite_type == "clarification_required"
    assert result.entities["policy_no"] == "9200100000458846"
    assert result.entities["endorseType"] == "001028"
    assert result.missing_required_entities == ["apply_seq"]
    assert result.need_clarification is True


async def test_new_strong_anchor_does_not_inherit_multiple_historical_policy_numbers():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite(
        "受理号 930010412672222 查一下",
        recent_messages=[
            {"role": "user", "content": "保单号 9200100000458846", "metadata": {}},
            {"role": "assistant", "content": "已记录第一个保单。", "metadata": {"need_clarification": False}},
            {"role": "user", "content": "保单号 9200100000458847", "metadata": {}},
            {"role": "assistant", "content": "已记录第二个保单。", "metadata": {"need_clarification": False}},
        ],
    )

    assert result.rewrite_type == "new_request"
    assert result.entities == {"apply_seq": "930010412672222"}
    assert result.inherited_entities == {}
    assert EntityBag(**result.entity_bag).to_compact_dict() == {"apply_seq": "930010412672222"}
    assert result.need_clarification is False


async def test_ordinal_reference_selects_matching_historical_entity():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite(
        "第二个保单的受理号 930010412672222 查一下",
        recent_messages=[
            {"role": "user", "content": "保单号 9200100000458846", "metadata": {}},
            {"role": "assistant", "content": "已记录第一个保单。", "metadata": {"need_clarification": False}},
            {"role": "user", "content": "保单号 9200100000458847", "metadata": {}},
            {"role": "assistant", "content": "已记录第二个保单。", "metadata": {"need_clarification": False}},
        ],
    )

    assert result.rewrite_type == "contextual_follow_up"
    assert result.entities["policy_no"] == "9200100000458847"
    assert result.entities["apply_seq"] == "930010412672222"
    assert result.inherited_entities["policy_no"] == "9200100000458847"


async def test_current_entity_has_priority_over_historical_same_type():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite(
        "这个保单改成查 9200100000458847",
        recent_messages=[{"role": "user", "content": "保单号 9200100000458846", "metadata": {}}],
    )

    assert result.entities["policy_no"] == "9200100000458847"
    assert "policy_no" not in result.inherited_entities


async def test_current_correction_query_uses_corrected_entity_value():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite(
        "不是保单9200100000458846，是9200100000458847，继续查",
        recent_messages=[{"role": "user", "content": "保单号 9200100000458846", "metadata": {}}],
    )

    assert result.entities["policy_no"] == "9200100000458847"
    assert result.need_clarification is False


async def test_follow_up_rewrite_uses_focused_latest_answer_summary():
    node = QueryRewriteNode(llm_provider=InvalidJsonLLM())
    result = await node.rewrite(
        "那这个一般是谁的问题？",
        recent_messages=[
            {"role": "user", "content": "REQ_001 为什么返回 E102？", "metadata": {}},
            {
                "role": "assistant",
                "content": "E102 通常表示签名校验失败。若 MCP workflow 显示退保任务卡住，需要继续核对上下游任务状态。",
                "metadata": {"need_clarification": False},
            },
        ],
    )

    assert result.rewrite_type == "contextual_follow_up"
    assert "上一轮回答摘要：E102 通常表示签名校验失败。" in result.rewritten_query
    assert "退保任务" not in result.rewritten_query
    assert "当前追问：那这个一般是谁的问题？" in result.rewritten_query
