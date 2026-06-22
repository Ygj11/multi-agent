import json
import re

from app.evaluation.runner import PromptEvalRunner
from app.llm.schemas import LLMResponse
from app.prompts.manifest import PromptManifest


class EvalFakeProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.messages = []

    async def chat(self, messages, tools=None, **kwargs):
        self.calls += 1
        self.messages.append(messages)
        if self.calls == 1:
            payload = {
                "is_follow_up": True,
                "rewritten_query": "保单 9200100000458846 保全完成后未更新，用户补充 endorseType=001028",
                "rewrite_type": "clarification_reply",
                "entities": {"policy_no": "9200100000458846", "endorseType": "001028"},
                "inherited_entities": {"policy_no": "9200100000458846"},
                "missing_required_entities": [],
                "need_clarification": False,
                "confidence": 0.91,
                "reason": "fake eval",
            }
        else:
            payload = {
                "is_follow_up": False,
                "rewritten_query": "保单 9200100000458847 查一下保全状态",
                "rewrite_type": "new_request",
                "entities": {"policy_no": "9200100000458847"},
                "inherited_entities": {},
                "missing_required_entities": [],
                "need_clarification": False,
                "confidence": 0.92,
                "reason": "fake eval",
            }
        return LLMResponse(content=json.dumps(payload, ensure_ascii=False), finish_reason="stop", model="fake")


def test_eval_cases_load_and_map_to_manifest_scenes():
    manifest = PromptManifest.load()
    runner = PromptEvalRunner(manifest=manifest)

    suites = runner.load_suites()

    assert suites
    assert {suite.scene for suite in suites}.issubset(manifest.scenes)
    for suite in suites:
        assert suite.suite == manifest.scene(suite.scene).eval_suite
        assert len({case.id for case in suite.cases}) == len(suite.cases)


def test_eval_runner_executes_fixture_checks():
    report = PromptEvalRunner().run()

    assert report.total > 0
    assert report.failed == 0
    assert report.passed == report.total


def test_eval_runner_can_execute_one_suite():
    report = PromptEvalRunner().run(suite_name="query_rewrite_multiturn_v1")

    assert report.total == 2
    assert report.failed == 0
    assert report.suites[0].suite == "query_rewrite_multiturn_v1"


async def test_eval_runner_can_execute_with_injected_provider():
    provider = EvalFakeProvider()

    report = await PromptEvalRunner().run_with_provider(
        provider,
        suite_name="query_rewrite_multiturn_v1",
    )

    assert report.total == 2
    assert report.failed == 0
    assert provider.calls == 2
    rendered = "\n".join(message["content"] for call in provider.messages for message in call)
    assert not re.search(r"\{[A-Za-z_][A-Za-z0-9_]*\}", rendered)
