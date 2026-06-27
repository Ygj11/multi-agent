from app.evaluation.agent.runner import AgentEvalRunner


async def test_agent_eval_runner_executes_first_pass_case(tmp_path):
    report = await AgentEvalRunner(work_dir=tmp_path).run(
        suite_name="verify_repair_core",
        case_id="aftercare_first_pass",
    )

    assert report.failed == 0
    case = report.suites[0].cases[0]
    assert case.trace.selected_agent == "troubleshooting_agent"
    assert case.trace.selected_skill_id == "troubleshooting_agent.endo_completion_aftercare"
    assert case.trace.final_task_completion_status == "PASS"
    assert "verify_task_completion" in case.trace.graph_path
    assert "dispatch_repair_agent" not in case.trace.graph_path


async def test_agent_eval_runner_executes_approval_callback_case(tmp_path):
    report = await AgentEvalRunner(work_dir=tmp_path).run(
        suite_name="verify_repair_approval",
        case_id="approval_callback_then_pass",
    )

    assert report.failed == 0
    case = report.suites[0].cases[0]
    assert case.trace.callback_statuses[-1] == "completed"
    assert case.trace.final_task_completion_status == "PASS"
    assert "resume_approved_tool" in case.trace.graph_path
    assert "verify_task_completion" in case.trace.graph_path


async def test_agent_eval_runner_fail_closed_invalid_verifier_json(tmp_path):
    report = await AgentEvalRunner(work_dir=tmp_path).run(
        suite_name="verify_repair_safety",
        case_id="verifier_invalid_json_fail_closed",
    )

    assert report.failed == 0
    case = report.suites[0].cases[0]
    assert case.trace.final_task_completion_status == "HUMAN_HANDOFF"
    assert case.trace.final_outcome == "human_handoff"
    assert "build_handoff_answer" in case.trace.graph_path
