from __future__ import annotations

"""Agent Eval baseline 和硬门禁。"""

import json
from pathlib import Path

from app.evaluation.agent.schemas import AgentEvalReport


HARD_GATE_FIELDS = {
    "verifier_false_pass_rate": 0.0,
    "infinite_loop_count": 0,
    "max_repair_round_violation_count": 0,
    "agent_drift_count": 0,
    "skill_drift_count": 0,
    "approval_bypass_count": 0,
}


def enforce_thresholds(report: AgentEvalReport, thresholds: dict[str, float | int] | None = None) -> list[str]:
    """检查 CI 硬门禁，返回错误列表。"""
    thresholds = thresholds or HARD_GATE_FIELDS
    payload = report.metrics.model_dump()
    errors: list[str] = []
    for field, expected_max in thresholds.items():
        actual = payload.get(field)
        if actual is None:
            errors.append(f"unknown metric threshold field: {field}")
            continue
        if float(actual) > float(expected_max):
            errors.append(f"{field} must be <= {expected_max}, got {actual}")
    return errors


def load_baseline(path: Path) -> AgentEvalReport:
    return AgentEvalReport.model_validate(json.loads(path.read_text(encoding="utf-8")))


def compare_baseline(report: AgentEvalReport, baseline: AgentEvalReport) -> list[str]:
    """比较 case pass/fail 是否相对 baseline 退化。"""
    current = _case_statuses(report)
    previous = _case_statuses(baseline)
    errors: list[str] = []
    for case_id, passed in previous.items():
        if case_id not in current:
            errors.append(f"baseline case missing in current report: {case_id}")
        elif passed and not current[case_id]:
            errors.append(f"case regressed from pass to fail: {case_id}")
    for case_id in sorted(set(current) - set(previous)):
        errors.append(f"new case absent from baseline: {case_id}")
    return errors


def _case_statuses(report: AgentEvalReport) -> dict[str, bool]:
    return {
        case.case_id: case.passed
        for suite in report.suites
        for case in suite.cases
    }
