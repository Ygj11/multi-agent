from __future__ import annotations

"""Agent Eval 断言集合。"""

import json
from typing import Any

from app.evaluation.agent.schemas import (
    AgentEvalAssertionFailure,
    AgentEvalCase,
    AgentEvalTrace,
)


class AgentEvalAssertions:
    """把 expected 与真实运行轨迹做对比。"""

    @classmethod
    def assert_case(cls, case: AgentEvalCase, trace: AgentEvalTrace) -> list[AgentEvalAssertionFailure]:
        failures: list[AgentEvalAssertionFailure] = []
        expected = case.expected
        cls._eq(failures, "selected_agent", expected.selected_agent, trace.selected_agent)
        cls._eq(failures, "selected_skill_id", expected.selected_skill_id, trace.selected_skill_id)
        cls._eq(failures, "final_outcome", expected.final_outcome, trace.final_outcome)
        cls._eq(failures, "approval_required", expected.approval_required, trace.approval_required)
        cls._eq(failures, "approval_status", expected.approval_status, trace.approval_status)
        callback_status = trace.callback_statuses[-1] if trace.callback_statuses else None
        cls._eq(failures, "callback_final_status", expected.callback_final_status, callback_status)
        cls._eq(failures, "repair_count", expected.repair_count, trace.repair_round)
        cls._eq(failures, "final_verifier_status", expected.final_verifier_status, trace.final_task_completion_status)
        first_status = trace.task_completion_statuses[0] if trace.task_completion_statuses else None
        cls._eq(failures, "initial_verifier_status", expected.initial_verifier_status, first_status)
        cls._eq(failures, "compliance_action", expected.compliance_action, trace.pre_answer_action)

        for status in expected.completion_status_must_not:
            if status in trace.task_completion_statuses:
                failures.append(cls._failure("completion_status_must_not", status, trace.task_completion_statuses))

        for node in expected.graph_path_must_include:
            if node not in trace.graph_path:
                failures.append(cls._failure("graph_path_must_include", node, trace.graph_path))
        for node in expected.graph_path_must_not_include:
            if node in trace.graph_path:
                failures.append(cls._failure("graph_path_must_not_include", node, trace.graph_path))

        tool_names = [str(item.get("tool_name") or item.get("name")) for item in trace.tool_calls]
        for tool_name in expected.tool_calls_must_include:
            if tool_name not in tool_names:
                failures.append(cls._failure("tool_calls_must_include", tool_name, tool_names))

        for tool_name in expected.tool_calls_must_not_repeat:
            duplicates = cls._duplicate_successful_calls(trace.tool_calls, tool_name)
            if duplicates:
                failures.append(cls._failure("tool_calls_must_not_repeat", tool_name, duplicates))
        for tool_name in expected.forbidden_duplicate_actions:
            duplicates = cls._duplicate_successful_calls(trace.tool_calls, tool_name)
            if duplicates:
                failures.append(cls._failure("forbidden_duplicate_actions", tool_name, duplicates))

        if expected.max_repair_round is not None and trace.repair_round > expected.max_repair_round:
            failures.append(cls._failure("max_repair_round", expected.max_repair_round, trace.repair_round))

        if expected.approval_pending_skips_completion_verify and not cls._pending_skipped_completion(trace.graph_path):
            failures.append(
                cls._failure(
                    "approval_pending_skips_completion_verify",
                    "no verify_task_completion after pause_for_approval",
                    trace.graph_path,
                )
            )

        if expected.no_agent_drift and trace.state_summary.get("agent_drift"):
            failures.append(cls._failure("no_agent_drift", False, trace.state_summary.get("agent_sequence")))
        if expected.no_skill_drift and trace.state_summary.get("skill_drift"):
            failures.append(cls._failure("no_skill_drift", False, trace.state_summary.get("skill_sequence")))

        answer = trace.answer or ""
        for token in expected.answer_must_include:
            if token not in answer:
                failures.append(cls._failure("answer_must_include", token, answer))
        for token in expected.answer_must_not_include:
            if token in answer:
                failures.append(cls._failure("answer_must_not_include", token, answer))
        return failures

    @staticmethod
    def _eq(
        failures: list[AgentEvalAssertionFailure],
        assertion: str,
        expected: Any,
        actual: Any,
    ) -> None:
        if expected is None:
            return
        if expected != actual:
            failures.append(AgentEvalAssertions._failure(assertion, expected, actual))

    @staticmethod
    def _failure(assertion: str, expected: Any, actual: Any) -> AgentEvalAssertionFailure:
        return AgentEvalAssertionFailure(
            assertion=assertion,
            expected=expected,
            actual=actual,
            message=f"{assertion} expected {expected!r}, got {actual!r}",
        )

    @staticmethod
    def _duplicate_successful_calls(tool_calls: list[dict[str, Any]], tool_name: str) -> list[dict[str, Any]]:
        seen: dict[str, int] = {}
        duplicates: list[dict[str, Any]] = []
        for item in tool_calls:
            name = str(item.get("tool_name") or item.get("name") or "")
            if name != tool_name or item.get("success") is not True:
                continue
            arguments = item.get("arguments")
            if arguments is None and item.get("arguments_json"):
                try:
                    arguments = json.loads(str(item["arguments_json"]))
                except json.JSONDecodeError:
                    arguments = item.get("arguments_json")
            key = json.dumps(arguments or {}, sort_keys=True, ensure_ascii=False, default=str)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                duplicates.append({"tool_name": tool_name, "arguments": arguments})
        return duplicates

    @staticmethod
    def _pending_skipped_completion(graph_path: list[str]) -> bool:
        if "pause_for_approval" not in graph_path:
            return False
        pause_index = len(graph_path) - 1 - list(reversed(graph_path)).index("pause_for_approval")
        return "verify_task_completion" not in graph_path[pause_index + 1 :]
