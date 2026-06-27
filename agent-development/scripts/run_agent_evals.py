from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.agent.baseline import compare_baseline, enforce_thresholds, load_baseline
from app.evaluation.agent.report import AgentEvalReportRenderer
from app.evaluation.agent.runner import DEFAULT_AGENT_CASES_ROOT, run_agent_eval_sync


def main() -> int:
    parser = argparse.ArgumentParser(description="Run end-to-end Agent behavior eval suites.")
    parser.add_argument("--suite", help="Run one agent eval suite by name.")
    parser.add_argument("--case", help="Run one case id.")
    parser.add_argument("--cases-root", type=Path, default=DEFAULT_AGENT_CASES_ROOT)
    parser.add_argument("--report-dir", type=Path, help="Write JSON and Markdown reports to this directory.")
    parser.add_argument("--baseline", type=Path, help="Compare against a baseline JSON report.")
    parser.add_argument("--update-baseline", type=Path, help="Write current report as a new baseline JSON.")
    parser.add_argument("--no-thresholds", action="store_true", help="Skip hard gate threshold checks.")
    args = parser.parse_args()

    with redirect_stdout(sys.stderr):
        report = run_agent_eval_sync(suite_name=args.suite, case_id=args.case, cases_root=args.cases_root)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))

    if args.report_dir:
        AgentEvalReportRenderer.write_json(report, args.report_dir / "agent_eval_report.json")
        AgentEvalReportRenderer.write_markdown(report, args.report_dir / "agent_eval_report.md")
    if args.update_baseline:
        AgentEvalReportRenderer.write_json(report, args.update_baseline)

    errors: list[str] = []
    if args.baseline:
        errors.extend(compare_baseline(report, load_baseline(args.baseline)))
    if not args.no_thresholds:
        errors.extend(enforce_thresholds(report))
    if errors:
        print("\nAgent Eval gates failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    return 1 if report.failed or errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
