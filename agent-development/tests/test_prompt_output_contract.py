import re

import pytest

from app.prompts.output_contract import PromptOutputContractRenderer
from app.utils.json_utils import parse_json_object


def _example_json(contract: str) -> str:
    match = re.search(r"Example:\n(?P<json>\{.*\})", contract, re.DOTALL)
    assert match, contract
    return match.group("json")


def test_task_completion_output_contract_expands_repair_plan_and_status_values():
    contract = PromptOutputContractRenderer().render_for_schema("TaskCompletionLLMOutput")

    assert "Output contract: TaskCompletionLLMOutput" in contract
    assert "status" in contract
    assert "PASS" in contract
    assert "CONTINUE" in contract
    assert "NEED_USER" in contract
    assert "HUMAN_HANDOFF" in contract
    assert "FAILED" in contract
    assert "repair_plan" in contract
    assert "target_agent" in contract
    assert "selected_skill_id" in contract
    assert "Do not wrap it in Markdown" in contract
    assert parse_json_object(_example_json(contract)) is not None


def test_intent_output_contract_does_not_reintroduce_entities():
    contract = PromptOutputContractRenderer().render_for_schema("IntentRecognitionLLMOutput")

    assert "Output contract: IntentRecognitionLLMOutput" in contract
    assert "intent" in contract
    assert "sub_intent" in contract
    assert "selected_agent" not in contract
    assert "entities" not in contract


def test_query_rewrite_output_contract_lists_rewrite_type_values():
    contract = PromptOutputContractRenderer().render_for_schema("QueryRewriteLLMOutput")

    assert "Output contract: QueryRewriteLLMOutput" in contract
    for value in ("direct", "contextual_follow_up", "clarification_reply", "new_request", "clarification_required"):
        assert value in contract


def test_text_schema_has_no_json_contract():
    assert PromptOutputContractRenderer().render_for_schema("text") == ""


def test_unknown_schema_fails_fast():
    with pytest.raises(ValueError, match="unknown prompt output schema"):
        PromptOutputContractRenderer().render_for_schema("UnknownSchema")
