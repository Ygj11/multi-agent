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
    assert result.data.entities == {}
    assert result.data.missing_required_entities == []

