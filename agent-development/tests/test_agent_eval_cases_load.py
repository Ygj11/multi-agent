from app.evaluation.agent.runner import AgentEvalRunner
from app.evaluation.prompts.runner import PromptEvalRunner


def test_agent_eval_cases_load_and_ids_are_unique():
    suites = AgentEvalRunner().load_suites()

    assert {suite.suite for suite in suites} >= {
        "verify_repair_core",
        "verify_repair_approval",
        "verify_repair_safety",
    }
    all_case_ids = [case.case_id for suite in suites for case in suite.cases]
    assert len(all_case_ids) == len(set(all_case_ids))
    assert {
        "aftercare_first_pass",
        "aftercare_repair_then_pass",
        "aftercare_need_user",
        "repair_triggers_approval",
        "pending_approval_skips_completion",
        "approval_callback_then_pass",
        "state_probe_inconsistent_no_false_pass",
        "max_repair_rounds_stop",
        "no_progress_repair_stop",
        "verifier_invalid_json_fail_closed",
        "duplicate_dangerous_write_plan_blocked",
        "completion_pass_compliance_blocks_raw_tool",
    }.issubset(set(all_case_ids))


def test_prompt_eval_cases_still_load_after_agent_eval_addition():
    report = PromptEvalRunner().run(suite_name="query_rewrite_multiturn_v1")

    assert report.failed == 0
    assert report.total == 12


def test_prompt_eval_intent_suite_has_extended_coverage():
    report = PromptEvalRunner().run(suite_name="intent_taxonomy_v1")

    assert report.failed == 0
    assert report.total == 18
