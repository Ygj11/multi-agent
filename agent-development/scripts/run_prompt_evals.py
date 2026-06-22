from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.runner import PromptEvalRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic prompt eval fixtures.")
    parser.add_argument("--suite", help="Run one eval suite by name.")
    parser.add_argument(
        "--provider",
        choices=("fixture", "real"),
        default="fixture",
        help="fixture validates local cases only; real calls the configured LLM provider.",
    )
    args = parser.parse_args()

    runner = PromptEvalRunner()
    if args.provider == "real":
        from app.config.settings import get_settings
        from app.llm.factory import build_llm_provider

        report = asyncio.run(runner.run_with_provider(build_llm_provider(get_settings()), suite_name=args.suite))
    else:
        report = runner.run(suite_name=args.suite)
    print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
