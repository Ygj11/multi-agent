from app.evaluation.agent.report import AgentEvalReportRenderer
from app.evaluation.agent.runner import AgentEvalRunner


async def test_agent_eval_report_can_render_markdown(tmp_path):
    report = await AgentEvalRunner(work_dir=tmp_path).run(
        suite_name="verify_repair_core",
        case_id="aftercare_first_pass",
    )

    markdown = AgentEvalReportRenderer.to_markdown(report)

    assert "# Agent Eval Report" in markdown
    assert "aftercare_first_pass" in markdown


async def test_agent_eval_report_writes_files(tmp_path):
    report = await AgentEvalRunner(work_dir=tmp_path).run(
        suite_name="verify_repair_core",
        case_id="aftercare_first_pass",
    )
    report_dir = tmp_path / "reports"

    AgentEvalReportRenderer.write_json(report, report_dir / "agent_eval_report.json")
    AgentEvalReportRenderer.write_markdown(report, report_dir / "agent_eval_report.md")

    assert (report_dir / "agent_eval_report.json").exists()
    assert (report_dir / "agent_eval_report.md").exists()


async def test_agent_eval_report_includes_verifier_metrics(tmp_path):
    report = await AgentEvalRunner(work_dir=tmp_path).run()

    assert report.metrics.verifier_pass_accuracy > 0
    assert report.metrics.verifier_incomplete_detection_rate > 0
    assert report.metrics.verifier_false_pass_rate == 0
    assert report.metrics.verifier_false_continue_rate == 0
