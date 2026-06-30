from __future__ import annotations

"""动态端到端 Agent Eval runner。

Dynamic E2E Eval 与 `app.evaluation.agent` 的区别：
1. 不读取 Fake LLM 脚本；
2. 默认使用项目 `.env` 构建真实 LLM Provider；
3. 可选择从 FastAPI `/api/chat` 入口或 Orchestrator 入口执行；
4. 仍复用 AgentEval 的 trace/assertion/report 模型，避免重复定义指标。
"""

import asyncio
import json
import os
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Any
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

from app.adapters.request_adapter import RequestAdapter
from app.config.settings import Settings
from app.evaluation.agent.assertions import AgentEvalAssertions
from app.evaluation.agent.report import build_report, build_suite_result
from app.evaluation.agent.runner import _contains_reason, _duplicate_success_count, _looks_like_write_tool
from app.evaluation.agent.schemas import (
    AgentEvalCaseResult,
    AgentEvalLLMCallTrace,
    AgentEvalReport,
    AgentEvalTrace,
)
from app.evaluation.e2e.schemas import DynamicE2ECase, DynamicE2ESuite
from app.schemas.enums.approval import ApprovalStatus
from app.schemas.enums.graph import GraphNode
from app.schemas.enums.task_completion import TaskCompletionStatus
from app.schemas.enums.verification import VerificationAction
from app.schemas.message import ChatRequest


E2E_EVALUATION_ROOT = Path(__file__).resolve().parent
DEFAULT_E2E_CASES_ROOT = E2E_EVALUATION_ROOT / "cases"


DEFAULT_ENV = {
    "APP_ENV": "test",
    "AUTH_MODE": "dev_header",
    "ALLOW_REQUEST_BODY_IDENTITY_FALLBACK": "true",
    "ENABLE_MCP_CLIENT": "false",
    "ENABLE_KNOWLEDGE_API": "false",
    "LOG_GRAPH_NODE_EVENTS": "false",
}


class DynamicE2EEvalRunner:
    """运行真实 LLM 参与的端到端 Agent Eval。

    `llm_provider_factory` 只用于测试或本地受控实验；正常使用时不传该参数，
    runner 会按项目 `.env` 经由 `build_llm_provider(settings)` 构建真实 provider。
    """

    def __init__(
        self,
        *,
        cases_root: Path = DEFAULT_E2E_CASES_ROOT,
        work_dir: Path | None = None,
        llm_provider_factory: Callable[[Settings], Any] | None = None,
    ) -> None:
        self.cases_root = Path(cases_root)
        self.work_dir = Path(work_dir) if work_dir else None
        self.llm_provider_factory = llm_provider_factory

    def load_suites(self) -> list[DynamicE2ESuite]:
        suites: list[DynamicE2ESuite] = []
        for path in sorted(self.cases_root.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"dynamic e2e suite root must be a mapping: {path}")
            suites.append(DynamicE2ESuite(**raw))
        if not suites:
            raise ValueError(f"no dynamic e2e suites found under {self.cases_root}")
        return suites

    async def run(self, suite_name: str | None = None, case_id: str | None = None) -> AgentEvalReport:
        suites = self.load_suites()
        if suite_name:
            suites = [suite for suite in suites if suite.suite == suite_name]
            if not suites:
                raise ValueError(f"dynamic e2e suite not found: {suite_name}")
        suite_results = []
        for suite in suites:
            cases = suite.cases
            if case_id:
                cases = [case for case in cases if case.case_id == case_id]
            if case_id and not cases:
                continue
            results = [await self.run_case(suite.suite, case) for case in cases]
            suite_results.append(build_suite_result(suite.suite, results))
        if case_id and not suite_results:
            raise ValueError(f"dynamic e2e case not found: {case_id}")
        return build_report(suite_results)

    async def run_case(self, suite: str, case: DynamicE2ECase) -> AgentEvalCaseResult:
        started = perf_counter()
        errors: list[str] = []
        trace = AgentEvalTrace()
        env = {**DEFAULT_ENV, **case.settings_overrides}

        with tempfile.TemporaryDirectory(prefix=f"dynamic_e2e_{case.case_id}_", dir=self.work_dir) as temp_dir:
            db_path = Path(temp_dir) / f"{self._safe_name(case.case_id)}.sqlite3"
            with _temporary_environ(env):
                provider_patch = self._provider_patch()
                with provider_patch:
                    container = None
                    try:
                        from app.main import create_app

                        app = create_app(sqlite_db_path=db_path)
                        container = app.state.container
                        if case.transport == "http":
                            state = await self._run_http(app, case)
                        else:
                            await container.startup()
                            state = await self._run_orchestrator(container, case)
                        trace = await self._build_trace(
                            container=container,
                            state=state,
                            transport=case.transport,
                            llm_mode=case.llm_mode,
                        )
                    except Exception as exc:
                        errors.append(f"{exc.__class__.__name__}: {exc}")
                    finally:
                        if container is not None and case.transport != "http":
                            await container.shutdown()

        assertion_failures = [] if errors else AgentEvalAssertions.assert_case(case, trace)  # type: ignore[arg-type]
        duration_ms = int((perf_counter() - started) * 1000)
        return AgentEvalCaseResult(
            case_id=case.case_id,
            suite=suite,
            passed=not errors and not assertion_failures,
            errors=errors,
            assertion_failures=assertion_failures,
            trace=trace,
            duration_ms=duration_ms,
            risk_level=case.risk_level,
            tags=case.tags,
            expected_initial_verifier_status=case.expected.initial_verifier_status,
            expected_final_verifier_status=case.expected.final_verifier_status,
        )

    def _provider_patch(self):
        """测试注入 provider 时，从 container 构建源头替换，而不是事后替换单个字段。"""
        if self.llm_provider_factory is None:
            return _noop_context()
        return patch("app.bootstrap.container.build_llm_provider", side_effect=self.llm_provider_factory)

    async def _run_orchestrator(self, container: Any, case: DynamicE2ECase) -> dict[str, Any]:
        request = ChatRequest(**case.input.model_dump(mode="json"))
        inbound = RequestAdapter().adapt(request)
        return await container.orchestrator.run(inbound)

    async def _run_http(self, app: Any, case: DynamicE2ECase) -> dict[str, Any]:
        """通过 FastAPI `/api/chat` 入口执行，并从 checkpoint 读取内部轨迹。"""
        with TestClient(app) as client:
            response = client.post("/api/chat", json=case.input.model_dump(mode="json"))
            response.raise_for_status()
            payload = response.json()
            container = app.state.container
            thread_id = f"{payload['session_key']}:{payload['request_id']}"
            snapshot = await container.storage.checkpoint_store.load(thread_id)
            if snapshot:
                return snapshot
            return {
                "request_id": payload["request_id"],
                "session_key": payload["session_key"],
                "original_query": payload["original_query"],
                "rewritten_query": payload["rewritten_query"],
                "intent": payload["intent"],
                "answer": payload["answer"],
                "approval_required": payload.get("approval_required", False),
                "approval_id": payload.get("approval_id"),
                "approval_status": payload.get("approval_status"),
                "graph_path": [],
            }

    async def _build_trace(
        self,
        *,
        container: Any,
        state: dict[str, Any],
        transport: str,
        llm_mode: str,
    ) -> AgentEvalTrace:
        session_key = str(state.get("session_key") or "")
        tool_logs = await container.storage.tool_execution_log_store.list_by_session(session_key) if session_key else []
        messages = await container.storage.message_store.list_by_session(session_key) if session_key else []
        assistant_metadata = [
            message.get("metadata") or {}
            for message in messages
            if message.get("role") == "assistant"
        ]
        parsed_tool_logs = [self._parse_tool_log(item) for item in tool_logs]
        completion_statuses = self._completion_statuses(state, assistant_metadata)
        pre_answer = state.get("pre_answer_verification_result") if isinstance(state.get("pre_answer_verification_result"), dict) else {}
        final_status = self._final_completion_status(state, completion_statuses)
        graph_path = [str(item) for item in state.get("graph_path") or []]
        selected_skill_id = state.get("selected_skill_id")
        selected_agent = state.get("selected_agent")
        state_summary = self._state_summary(state, parsed_tool_logs)
        state_summary.update({"transport": transport, "llm_mode": llm_mode})
        return AgentEvalTrace(
            request_id=state.get("request_id"),
            session_key=session_key,
            answer=state.get("answer"),
            graph_path=graph_path,
            selected_agent=selected_agent,
            selected_skill_id=selected_skill_id,
            repair_round=int(state.get("repair_round") or 0),
            task_completion_statuses=completion_statuses,
            final_task_completion_status=final_status,
            pre_answer_action=pre_answer.get("action") or self._metadata_value(assistant_metadata, "pre_answer_action"),
            approval_required=bool(state.get("approval_required")),
            approval_id=state.get("approval_id"),
            approval_status=state.get("approval_status"),
            callback_statuses=[],
            final_outcome=self._final_outcome(state, final_status),
            tool_calls=parsed_tool_logs,
            llm_calls=self._llm_call_trace(container),
            assistant_message_metadata=assistant_metadata,
            state_summary=state_summary,
        )

    @staticmethod
    def _llm_call_trace(container: Any) -> list[AgentEvalLLMCallTrace]:
        calls = getattr(container.llm_provider, "calls", None)
        if not isinstance(calls, list):
            return []
        traces: list[AgentEvalLLMCallTrace] = []
        for item in calls:
            if isinstance(item, AgentEvalLLMCallTrace):
                traces.append(item)
            elif isinstance(item, dict):
                traces.append(
                    AgentEvalLLMCallTrace(
                        scene=str(item.get("scene")) if item.get("scene") is not None else None,
                        tool_names=[
                            str(tool.get("function", {}).get("name") or tool.get("name"))
                            for tool in item.get("tools") or []
                            if isinstance(tool, dict)
                        ],
                    )
                )
        return traces

    @staticmethod
    def _completion_statuses(state: dict[str, Any], assistant_metadata: list[dict[str, Any]]) -> list[str]:
        statuses: list[str] = []
        for item in state.get("repair_history") or []:
            if isinstance(item, dict) and item.get("status"):
                statuses.append(str(item["status"]))
        completion = state.get("task_completion_verification_result")
        if isinstance(completion, dict) and completion.get("status"):
            statuses.append(str(completion["status"]))
        if state.get("task_completion_status"):
            statuses.append(str(state["task_completion_status"]))
        for metadata in assistant_metadata:
            if metadata.get("task_completion_status"):
                statuses.append(str(metadata["task_completion_status"]))
        deduped: list[str] = []
        for status in statuses:
            if not deduped or deduped[-1] != status:
                deduped.append(status)
        return deduped

    @staticmethod
    def _final_completion_status(state: dict[str, Any], statuses: list[str]) -> str | None:
        completion = state.get("task_completion_verification_result")
        if isinstance(completion, dict) and completion.get("status"):
            return str(completion["status"])
        if state.get("task_completion_status"):
            return str(state["task_completion_status"])
        return statuses[-1] if statuses else None

    @staticmethod
    def _final_outcome(state: dict[str, Any], final_completion_status: str | None):
        graph_path = state.get("graph_path") or []
        pre_answer = state.get("pre_answer_verification_result") if isinstance(state.get("pre_answer_verification_result"), dict) else {}
        if state.get("approval_required") and state.get("approval_status") == ApprovalStatus.PENDING:
            return "approval_pending"
        if GraphNode.REGENERATE_COMPLIANT_ANSWER in graph_path or (
            pre_answer.get("action") == VerificationAction.RETRY and GraphNode.FALLBACK_ANSWER in graph_path
        ):
            return "compliance_blocked"
        if final_completion_status == TaskCompletionStatus.NEED_USER or state.get("clarification_source") == "task_completion_verification":
            return "need_user"
        if final_completion_status == TaskCompletionStatus.HUMAN_HANDOFF or state.get("manual_intervention_required"):
            return "human_handoff"
        if final_completion_status == TaskCompletionStatus.FAILED or state.get("error"):
            return "failed"
        return "answered"

    @staticmethod
    def _state_summary(state: dict[str, Any], tool_logs: list[dict[str, Any]]) -> dict[str, Any]:
        duplicate_count = _duplicate_success_count(tool_logs)
        approval_bypass = any(
            _looks_like_write_tool(item.get("tool_name"))
            and item.get("success") is True
            and not item.get("approval_id")
            for item in tool_logs
        )
        return {
            "duplicate_tool_call_count": duplicate_count,
            "approval_bypass": approval_bypass,
            "max_repair_round_violation": int(state.get("repair_round") or 0) > 2,
            "no_progress_terminated": _contains_reason(state, "task_completion_repair_no_progress"),
            "infinite_loop_detected": int(state.get("repair_round") or 0) > 10,
        }

    @staticmethod
    def _parse_tool_log(item: dict[str, Any]) -> dict[str, Any]:
        parsed = dict(item)
        for source_key, target_key in (("arguments_json", "arguments"), ("result_json", "result")):
            raw = parsed.get(source_key)
            if raw is None:
                continue
            try:
                parsed[target_key] = json.loads(str(raw))
            except json.JSONDecodeError:
                parsed[target_key] = raw
        return parsed

    @staticmethod
    def _metadata_value(metadata: list[dict[str, Any]], key: str) -> Any:
        for item in reversed(metadata):
            if key in item:
                return item[key]
        return None

    @staticmethod
    def _safe_name(value: str) -> str:
        return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


@contextmanager
def _temporary_environ(values: dict[str, str]):
    old_values = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = str(value)
        yield
    finally:
        for key, old in old_values.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


@contextmanager
def _noop_context():
    yield


def run_dynamic_e2e_eval_sync(
    *,
    suite_name: str | None = None,
    case_id: str | None = None,
    cases_root: Path = DEFAULT_E2E_CASES_ROOT,
    work_dir: Path | None = None,
) -> AgentEvalReport:
    """同步入口，供 CLI 或临时脚本调用。"""
    return asyncio.run(DynamicE2EEvalRunner(cases_root=cases_root, work_dir=work_dir).run(suite_name=suite_name, case_id=case_id))
