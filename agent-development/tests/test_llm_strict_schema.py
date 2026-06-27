import json

from app.llm.output_schemas import (
    IntentRecognitionLLMOutput,
    QueryRewriteLLMOutput,
    parse_llm_json_schema,
)


def test_strict_schema_detects_invalid_json():
    result = parse_llm_json_schema("not json", IntentRecognitionLLMOutput)

    assert result.success is False
    assert result.error_code == "llm_json_parse_failed"
    assert result.parse_status == "json_parse_failed"
    assert result.schema_name == "IntentRecognitionLLMOutput"


def test_strict_schema_detects_missing_required_fields():
    result = parse_llm_json_schema(json.dumps({"intent": "troubleshooting"}), IntentRecognitionLLMOutput)

    assert result.success is False
    assert result.error_code == "llm_schema_validation_failed"
    assert result.parse_status == "schema_validation_failed"
    assert "confidence" in (result.error_detail or "")


def test_strict_schema_rejects_unknown_fields():
    result = parse_llm_json_schema(
        json.dumps(
            {
                "is_follow_up": False,
                "rewritten_query": "查询保单状态",
                "rewrite_type": "new_request",
                "need_clarification": False,
                "confidence": 0.9,
                "unexpected": "field",
            },
            ensure_ascii=False,
        ),
        QueryRewriteLLMOutput,
    )

    assert result.success is False
    assert result.error_code == "llm_schema_validation_failed"
    assert "unexpected" in (result.error_detail or "")


def test_strict_schema_accepts_optional_defaults():
    result = parse_llm_json_schema(
        json.dumps(
            {
                "intent": "troubleshooting",
                "sub_intent": "endo_completion_aftercare",
                "confidence": 0.91,
                "need_clarification": False,
            }
        ),
        IntentRecognitionLLMOutput,
    )

    assert result.success is True
    assert isinstance(result.data, IntentRecognitionLLMOutput)
    assert "entities" not in result.data.model_dump()
    assert "missing_required_entities" not in result.data.model_dump()
    assert "is_follow_up" not in result.data.model_dump()


def test_intent_schema_rejects_legacy_entity_and_followup_fields():
    result = parse_llm_json_schema(
        json.dumps(
            {
                "intent": "troubleshooting",
                "sub_intent": "refund_failure",
                "confidence": 0.95,
                "entities": {"policy_no": "9200100000458846"},
                "missing_required_entities": [],
                "need_clarification": False,
                "is_follow_up": False,
                "reason": "legacy output",
            }
        ),
        IntentRecognitionLLMOutput,
    )

    assert result.success is False
    assert result.error_code == "llm_schema_validation_failed"
    assert "entities" in (result.error_detail or "")
    assert "missing_required_entities" in (result.error_detail or "")
    assert "is_follow_up" in (result.error_detail or "")
