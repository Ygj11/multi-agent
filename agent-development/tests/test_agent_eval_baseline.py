from app.evaluation.agent.baseline import compare_baseline, enforce_thresholds
from app.evaluation.agent.runner import AgentEvalRunner


async def test_agent_eval_thresholds_pass_for_core_case(tmp_path):
    report = await AgentEvalRunner(work_dir=tmp_path).run(
        suite_name="verify_repair_core",
        case_id="aftercare_first_pass",
    )

    assert enforce_thresholds(report) == []


async def test_agent_eval_baseline_detects_regression(tmp_path):
    baseline = await AgentEvalRunner(work_dir=tmp_path).run(
        suite_name="verify_repair_core",
        case_id="aftercare_first_pass",
    )
    current = baseline.model_copy(deep=True)
    current.suites[0].cases[0].passed = False
    current.suites[0].failed = 1
    current.failed = 1

    errors = compare_baseline(current, baseline)

    assert any("regressed" in error for error in errors)
