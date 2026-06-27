from __future__ import annotations

"""Agent Eval 报告与指标计算。"""

import json
from pathlib import Path

from app.evaluation.agent.schemas import (
    AgentEvalCaseResult,
    AgentEvalMetrics,
    AgentEvalReport,
    AgentEvalSuiteResult,
)


def compute_metrics(results: list[AgentEvalCaseResult]) -> AgentEvalMetrics:
    """从 case 结果计算行为级指标。"""
    total = len(results)
    passed = sum(1 for item in results if item.passed)
    failed = total - passed
    if total == 0:
        return AgentEvalMetrics()

    first_pass = sum(
        1
        for item in results
        if item.trace.final_task_completion_status == "PASS" and item.trace.repair_round == 0
    )
    repair_attempts = sum(1 for item in results if item.trace.repair_round > 0)
    repair_success = sum(
        1
        for item in results
        if item.trace.repair_round > 0 and item.trace.final_task_completion_status == "PASS"
    )
    human_handoff = sum(1 for item in results if item.trace.final_outcome == "human_handoff")
    need_user = sum(1 for item in results if item.trace.final_outcome == "need_user")
    final_pass = sum(1 for item in results if item.trace.final_task_completion_status == "PASS")
    duplicate_count = sum(1 for item in results if item.trace.state_summary.get("duplicate_tool_call_count", 0) > 0)
    verifier_expected = [item for item in results if item.expected_final_verifier_status]
    expected_pass = [item for item in verifier_expected if item.expected_final_verifier_status == "PASS"]
    expected_incomplete = [item for item in verifier_expected if item.expected_final_verifier_status != "PASS"]
    false_pass = sum(1 for item in expected_incomplete if item.trace.final_task_completion_status == "PASS")
    false_continue = sum(
        1
        for item in expected_pass
        if item.trace.final_task_completion_status in {"CONTINUE", "NEED_USER", "HUMAN_HANDOFF", "FAILED"}
    )

    return AgentEvalMetrics(
        total=total,
        passed=passed,
        failed=failed,
        first_pass_completion_rate=first_pass / total,
        first_pass_failure_rate=(total - first_pass) / total,
        verifier_pass_accuracy=(
            sum(1 for item in expected_pass if item.trace.final_task_completion_status == "PASS") / len(expected_pass)
            if expected_pass
            else 0.0
        ),
        verifier_incomplete_detection_rate=(
            sum(1 for item in expected_incomplete if item.trace.final_task_completion_status != "PASS") / len(expected_incomplete)
            if expected_incomplete
            else 0.0
        ),
        verifier_false_pass_rate=false_pass / len(expected_incomplete) if expected_incomplete else 0.0,
        verifier_false_continue_rate=false_continue / len(expected_pass) if expected_pass else 0.0,
        repair_attempt_rate=repair_attempts / total,
        repair_success_rate=(repair_success / repair_attempts) if repair_attempts else 0.0,
        average_repair_rounds=sum(item.trace.repair_round for item in results) / total,
        no_progress_termination_rate=sum(
            1
            for item in results
            if "task_completion_repair_no_progress" in item.trace.task_completion_statuses
            or item.trace.state_summary.get("no_progress_terminated")
        )
        / total,
        final_task_completion_rate=final_pass / total,
        final_failure_rate=sum(1 for item in results if item.trace.final_outcome in {"failed", "compliance_blocked"}) / total,
        human_handoff_rate=human_handoff / total,
        need_user_rate=need_user / total,
        average_tool_calls=sum(len(item.trace.tool_calls) for item in results) / total,
        duplicate_tool_call_rate=duplicate_count / total,
        average_llm_calls=sum(len(item.trace.llm_calls) for item in results) / total,
        average_latency_ms=sum(item.duration_ms for item in results) / total,
        infinite_loop_count=sum(1 for item in results if item.trace.state_summary.get("infinite_loop_detected")),
        max_repair_round_violation_count=sum(1 for item in results if item.trace.state_summary.get("max_repair_round_violation")),
        agent_drift_count=sum(1 for item in results if item.trace.state_summary.get("agent_drift")),
        skill_drift_count=sum(1 for item in results if item.trace.state_summary.get("skill_drift")),
        approval_bypass_count=sum(1 for item in results if item.trace.state_summary.get("approval_bypass")),
    )


def build_suite_result(suite: str, results: list[AgentEvalCaseResult]) -> AgentEvalSuiteResult:
    metrics = compute_metrics(results)
    return AgentEvalSuiteResult(
        suite=suite,
        total=metrics.total,
        passed=metrics.passed,
        failed=metrics.failed,
        metrics=metrics,
        cases=results,
    )


def build_report(suites: list[AgentEvalSuiteResult]) -> AgentEvalReport:
    all_results = [case for suite in suites for case in suite.cases]
    metrics = compute_metrics(all_results)
    return AgentEvalReport(
        total=metrics.total,
        passed=metrics.passed,
        failed=metrics.failed,
        metrics=metrics,
        suites=suites,
    )


class AgentEvalReportRenderer:
    """渲染 Agent Eval JSON/Markdown 报告。"""

    @staticmethod
    def write_json(report: AgentEvalReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def write_markdown(report: AgentEvalReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(AgentEvalReportRenderer.to_markdown(report), encoding="utf-8")

    @staticmethod
    def to_markdown(report: AgentEvalReport) -> str:
        lines = [
            "# Agent Eval Report",
            "",
            "## Summary",
            "",
            f"- Total: {report.total}",
            f"- Passed: {report.passed}",
            f"- Failed: {report.failed}",
            f"- Final task completion rate: {report.metrics.final_task_completion_rate:.2%}",
            f"- Repair success rate: {report.metrics.repair_success_rate:.2%}",
            f"- Verifier pass accuracy: {report.metrics.verifier_pass_accuracy:.2%}",
            f"- Verifier incomplete detection rate: {report.metrics.verifier_incomplete_detection_rate:.2%}",
            f"- Verifier false pass rate: {report.metrics.verifier_false_pass_rate:.2%}",
            f"- Verifier false continue rate: {report.metrics.verifier_false_continue_rate:.2%}",
            f"- Human handoff rate: {report.metrics.human_handoff_rate:.2%}",
            "",
            "## Suites",
            "",
        ]
        for suite in report.suites:
            lines.extend(
                [
                    f"### {suite.suite}",
                    "",
                    f"- Total: {suite.total}",
                    f"- Passed: {suite.passed}",
                    f"- Failed: {suite.failed}",
                    "",
                    "| Case | Result | Agent | Skill | Completion | Outcome | Errors |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                ]
            )
            for case in suite.cases:
                errors = "; ".join(case.errors + [failure.message for failure in case.assertion_failures])
                lines.append(
                    "| {case_id} | {result} | {agent} | {skill} | {completion} | {outcome} | {errors} |".format(
                        case_id=case.case_id,
                        result="PASS" if case.passed else "FAIL",
                        agent=case.trace.selected_agent or "",
                        skill=case.trace.selected_skill_id or "",
                        completion=case.trace.final_task_completion_status or "",
                        outcome=case.trace.final_outcome,
                        errors=errors.replace("|", "\\|"),
                    )
                )
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
