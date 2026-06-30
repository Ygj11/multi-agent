import json

from app.evaluation.e2e.runner import DynamicE2EEvalRunner
from app.evaluation.e2e.schemas import DynamicE2ECase, DynamicE2EExpected, DynamicE2EInput, DynamicE2EMessage
from app.llm.schemas import LLMResponse
from app.schemas.enums.llm import LLMScene


class RecordingLLMProvider:
    def __init__(self) -> None:
        self.calls = []

    async def chat(self, *, messages, tools=None, scene=None, **kwargs):
        self.calls.append({"scene": scene, "tools": tools or []})
        if scene == LLMScene.QUERY_REWRITE:
            return LLMResponse(
                content=json.dumps(
                    {
                        "is_follow_up": False,
                        "rewritten_query": "保全任务完成，保单9200100000458846，受理号930021042875719，保全项001028，为什么没有更新？",
                        "rewrite_type": "new_request",
                        "entities": {
                            "policy_no": "9200100000458846",
                            "apply_seq": "930021042875719",
                            "endorseType": "001028",
                        },
                        "inherited_entities": {},
                        "missing_required_entities": [],
                        "need_clarification": False,
                        "clarification_question": None,
                        "confidence": 0.9,
                        "reason": "dynamic_e2e_test",
                    },
                    ensure_ascii=False,
                ),
                model="recording",
            )
        if scene == LLMScene.INTENT_RECOGNITION:
            return LLMResponse(
                content=json.dumps(
                    {
                        "intent": "troubleshooting",
                        "sub_intent": "endo_completion_aftercare",
                        "confidence": 0.9,
                        "need_clarification": False,
                        "clarification_question": None,
                        "reason": "dynamic_e2e_test",
                    },
                    ensure_ascii=False,
                ),
                model="recording",
            )
        if scene == LLMScene.SUBAGENT_REASONING and tools and not any(message.get("role") == "tool" for message in messages):
            return LLMResponse(
                content=None,
                tool_calls=[
                    {
                        "id": "call_query_endo_task_record",
                        "type": "function",
                        "function": {
                            "name": "query_endo_task_record",
                            "arguments": json.dumps({"apply_seq": "930021042875719"}, ensure_ascii=False),
                        },
                    }
                ],
                has_tool_calls=True,
                finish_reason="tool_calls",
                model="recording",
            )
        return LLMResponse(content="真实模型回答：ok，已结合保全任务记录判断为保单更新失败。", model="recording")

    async def close(self) -> None:
        return None


def _case(*, transport: str = "orchestrator") -> DynamicE2ECase:
    return DynamicE2ECase(
        case_id=f"dynamic_{transport}",
        description="dynamic e2e runner test",
        transport=transport,
        input=DynamicE2EInput(
            tenant_id="pingan_health",
            channel="web",
            user_id="u001",
            session_id=f"s_{transport}",
            messages=[
                DynamicE2EMessage(
                    role="user",
                    content="保全任务完成，保单9200100000458846没有更新，受理号930021042875719，保全项001028",
                )
            ],
        ),
        expected=DynamicE2EExpected(
            final_outcome="answered",
            selected_agent="troubleshooting_agent",
            selected_skill_id="troubleshooting_agent.endo_completion_aftercare",
            tool_calls_must_include=["query_endo_task_record"],
            answer_must_include=["真实模型回答"],
        ),
        settings_overrides={
            "ENABLE_REAL_LLM": "true",
            "ENABLE_OPENSDK_LLM": "false",
            "INTERNAL_LLM_API_URL": "http://dynamic-e2e-llm.local/v1/chat",
            "ENABLE_TASK_COMPLETION_VERIFY": "false",
            "POS_TOOL_MODE": "mock",
            "TROUBLESHOOTING_TOOL_MODE": "mock",
        },
    )


async def test_dynamic_e2e_runner_uses_injected_real_provider_without_fake_replacement(tmp_path):
    provider = RecordingLLMProvider()
    runner = DynamicE2EEvalRunner(work_dir=tmp_path, llm_provider_factory=lambda settings: provider)

    report = await runner.run_case("dynamic", _case())

    assert provider.calls
    assert report.passed
    assert "真实模型回答：ok" in (report.trace.answer or "")
    assert report.trace.state_summary["llm_mode"] == "real"


async def test_dynamic_e2e_runner_can_enter_through_http_api(tmp_path):
    provider = RecordingLLMProvider()
    runner = DynamicE2EEvalRunner(work_dir=tmp_path, llm_provider_factory=lambda settings: provider)

    report = await runner.run_case("dynamic", _case(transport="http"))

    assert provider.calls
    assert report.passed
    assert report.trace.state_summary["transport"] == "http"
