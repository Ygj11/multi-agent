from __future__ import annotations

"""端到端 Agent 行为级 Eval runner。"""

import asyncio
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml

from app.adapters.request_adapter import RequestAdapter
from app.evaluation.agent.assertions import AgentEvalAssertions
from app.evaluation.agent.fake_llm import AgentEvalFakeLLM
from app.evaluation.agent.fixtures import AgentEvalFixtureApplier
from app.evaluation.agent.report import build_report, build_suite_result
from app.evaluation.agent.schemas import (
    AgentEvalCase,
    AgentEvalCaseResult,
    AgentEvalReport,
    AgentEvalSuite,
    AgentEvalTrace,
)
from app.schemas.approval import ApprovalCallbackRequest
from app.schemas.message import ChatRequest


AGENT_EVALUATION_ROOT = Path(__file__).resolve().parent
DEFAULT_AGENT_CASES_ROOT = AGENT_EVALUATION_ROOT / "cases"


DEFAULT_ENV = {
    "APP_ENV": "test",
    "AUTH_MODE": "dev_header",
    "ALLOW_REQUEST_BODY_IDENTITY_FALLBACK": "true",
    "INTERNAL_LLM_API_URL": "http://agent-eval-llm.local/v1/chat",
    "ENABLE_OPENSDK_LLM": "false",
    "ENABLE_MCP_CLIENT": "false",
    "ENABLE_KNOWLEDGE_API": "false",
    "ENABLE_TASK_COMPLETION_VERIFY": "true",
    "TASK_COMPLETION_ENABLE_LLM": "true",
    "TASK_COMPLETION_ENABLE_STATE_PROBES": "true",
    "ENABLE_SKILL_LLM_RERANK": "false",
    "POS_TOOL_MODE": "mock",
    "TROUBLESHOOTING_TOOL_MODE": "real",
    "TROUBLESHOOTING_API_BASE_URL": "http://agent-eval-troubleshooting.local",
    "LOG_GRAPH_NODE_EVENTS": "false",
}


class AgentEvalRunner:
    """加载案例、构建隔离 runtime、运行真实主图并执行断言。"""

    def __init__(
        self,
        *,
        cases_root: Path = DEFAULT_AGENT_CASES_ROOT,
        work_dir: Path | None = None,
    ) -> None:
        self.cases_root = Path(cases_root)
        self.work_dir = Path(work_dir) if work_dir else None

    def load_suites(self) -> list[AgentEvalSuite]:
        suites: list[AgentEvalSuite] = []
        for path in sorted(self.cases_root.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"agent eval suite root must be a mapping: {path}")
            suites.append(AgentEvalSuite(**raw))
        if not suites:
            raise ValueError(f"no agent eval suites found under {self.cases_root}")
        return suites

    async def run(self, suite_name: str | None = None, case_id: str | None = None) -> AgentEvalReport:
        suites = self.load_suites()
        if suite_name:
            suites = [suite for suite in suites if suite.suite == suite_name]
            if not suites:
                raise ValueError(f"agent eval suite not found: {suite_name}")
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
            raise ValueError(f"agent eval case not found: {case_id}")
        return build_report(suite_results)

    async def run_case(self, suite: str, case: AgentEvalCase) -> AgentEvalCaseResult:
        started = perf_counter()
        fake_llm = AgentEvalFakeLLM(case.llm_scripted_responses)
        trace = AgentEvalTrace()
        errors: list[str] = []
        applier: AgentEvalFixtureApplier | None = None
        container = None
        state: dict[str, Any] = {}

        env = {**DEFAULT_ENV, **case.settings_overrides}
        with tempfile.TemporaryDirectory(prefix=f"agent_eval_{case.case_id}_", dir=self.work_dir) as temp_dir:
            db_path = Path(temp_dir) / f"{self._safe_name(case.case_id)}.sqlite3"
            with _temporary_environ(env):
                try:
                    from app.main import create_app

                    app = create_app(sqlite_db_path=db_path)
                    container = app.state.container
                    container.llm_provider.chat = fake_llm.chat
                    applier = AgentEvalFixtureApplier(container)
                    applier.apply(
                        tool_fixtures=case.tool_fixtures,
                        approval_fixture=case.approval_fixtures,
                        business_state_fixtures=case.business_state_fixtures,
                    )
                    await container.startup()
                    await self._apply_session_fixtures(container, case)
                    request = ChatRequest(**case.input.model_dump())
                    inbound = RequestAdapter().adapt(request)
                    state = await container.orchestrator.run(inbound)
                    callback_statuses = await self._run_callbacks(container, case, state)
                    if callback_statuses:
                        snapshot = await container.storage.checkpoint_store.load(state.get("thread_id") or "")
                        state = snapshot or state
                    trace = await self._build_trace(
                        container=container,
                        state=state,
                        fake_llm=fake_llm,
                        callback_statuses=callback_statuses,
                    )
                except Exception as exc:
                    errors.append(f"{exc.__class__.__name__}: {exc}")
                    trace.llm_calls = fake_llm.calls
                finally:
                    if applier is not None:
                        errors.extend(applier.errors)
                    if container is not None:
                        await container.shutdown()

        assertion_failures = [] if errors else AgentEvalAssertions.assert_case(case, trace)
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

    async def _apply_session_fixtures(self, container: Any, case: AgentEvalCase) -> None:
        if case.session_fixtures is None:
            return
        session_key = RequestAdapter.build_session_key(
            case.input.tenant_id,
            case.input.channel,
            case.input.user_id,
            case.input.session_id,
        )
        for message in case.session_fixtures.recent_messages:
            await container.storage.message_store.append(
                session_key=session_key,
                role=message.role,
                content=message.content,
                metadata=message.metadata,
            )
        if case.session_fixtures.short_summary:
            summary = case.session_fixtures.short_summary
            updated_at = datetime.now(UTC).isoformat()

            def write(conn):
                conn.execute(
                    """
                    INSERT INTO short_term_memory(session_key, summary, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(session_key) DO UPDATE SET
                        summary = excluded.summary,
                        updated_at = excluded.updated_at
                    """,
                    (session_key, summary, updated_at),
                )

            await container.storage.db.run(write)

    async def _run_callbacks(
        self,
        container: Any,
        case: AgentEvalCase,
        state: dict[str, Any],
    ) -> list[str]:
        callbacks = case.approval_fixtures.callbacks if case.approval_fixtures else []
        statuses: list[str] = []
        current_approval_id = state.get("approval_id")
        for callback in callbacks:
            approval_id = callback.approval_id or current_approval_id
            if not approval_id:
                raise RuntimeError("approval callback requested but no approval_id is available")
            result = await container.approval_service.handle_callback(
                ApprovalCallbackRequest(
                    approval_id=approval_id,
                    external_approval_id=callback.external_approval_id or f"ext_{approval_id}",
                    status=callback.status,
                    approver=callback.approver,
                    comment=callback.comment,
                )
            )
            statuses.append(result.approval_request.status)
            current_approval_id = result.approval_request.next_approval_id or approval_id
        return statuses

    async def _build_trace(
        self,
        *,
        container: Any,
        state: dict[str, Any],
        fake_llm: AgentEvalFakeLLM,
        callback_statuses: list[str],
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
        if not selected_skill_id and isinstance(state.get("subagent_result"), dict):
            selected_skill_id = state["subagent_result"].get("selected_skill_id")
        selected_agent = state.get("selected_agent")
        answer = state.get("answer")
        trace = AgentEvalTrace(
            request_id=state.get("request_id"),
            session_key=session_key,
            answer=answer,
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
            callback_statuses=callback_statuses,
            final_outcome=self._final_outcome(state, final_status, callback_statuses),
            tool_calls=parsed_tool_logs,
            llm_calls=fake_llm.calls,
            assistant_message_metadata=assistant_metadata,
            state_summary=self._state_summary(state, parsed_tool_logs),
        )
        return trace

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
    def _final_outcome(
        state: dict[str, Any],
        final_completion_status: str | None,
        callback_statuses: list[str],
    ):
        graph_path = state.get("graph_path") or []
        pre_answer = state.get("pre_answer_verification_result") if isinstance(state.get("pre_answer_verification_result"), dict) else {}
        if state.get("approval_required") and state.get("approval_status") == "pending":
            return "approval_pending"
        if callback_statuses and callback_statuses[-1] == "completed":
            return "approval_completed"
        if "regenerate_compliant_answer" in graph_path or (pre_answer.get("action") == "retry" and "fallback_answer" in graph_path):
            return "compliance_blocked"
        if final_completion_status == "NEED_USER" or state.get("clarification_source") == "task_completion_verification":
            return "need_user"
        if final_completion_status == "HUMAN_HANDOFF" or state.get("manual_intervention_required"):
            return "human_handoff"
        if final_completion_status == "FAILED" or state.get("error"):
            return "failed"
        return "answered"

    @staticmethod
    def _state_summary(state: dict[str, Any], tool_logs: list[dict[str, Any]]) -> dict[str, Any]:
        agent_sequence: list[str] = []
        skill_sequence: list[str] = []
        for item in state.get("previous_subagent_results") or []:
            if isinstance(item, dict):
                if item.get("agent_name") or item.get("name"):
                    agent_sequence.append(str(item.get("agent_name") or item.get("name")))
                if item.get("selected_skill_id"):
                    skill_sequence.append(str(item["selected_skill_id"]))
        subagent_result = state.get("subagent_result") if isinstance(state.get("subagent_result"), dict) else {}
        if subagent_result.get("agent_name") or subagent_result.get("name"):
            agent_sequence.append(str(subagent_result.get("agent_name") or subagent_result.get("name")))
        if state.get("selected_agent") and not agent_sequence:
            agent_sequence.append(str(state["selected_agent"]))
        if subagent_result.get("selected_skill_id"):
            skill_sequence.append(str(subagent_result["selected_skill_id"]))
        if state.get("selected_skill_id") and not skill_sequence:
            skill_sequence.append(str(state["selected_skill_id"]))
        duplicate_count = _duplicate_success_count(tool_logs)
        approval_bypass = any(
            _looks_like_write_tool(item.get("tool_name"))
            and item.get("success") is True
            and not item.get("approval_id")
            for item in tool_logs
        )
        return {
            "agent_sequence": agent_sequence,
            "skill_sequence": skill_sequence,
            "agent_drift": len(set(agent_sequence)) > 1,
            "skill_drift": len(set(skill_sequence)) > 1,
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


def _duplicate_success_count(tool_logs: list[dict[str, Any]]) -> int:
    seen: dict[str, int] = {}
    duplicate = 0
    for item in tool_logs:
        if item.get("success") is not True:
            continue
        key = json.dumps(
            {"tool_name": item.get("tool_name"), "arguments": item.get("arguments")},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            duplicate += 1
    return duplicate


def _looks_like_write_tool(tool_name: Any) -> bool:
    name = str(tool_name or "")
    return name.startswith("notice_") or name == "policy_suspendOrRecovery"


def _contains_reason(state: dict[str, Any], reason: str) -> bool:
    completion = state.get("task_completion_verification_result")
    if isinstance(completion, dict) and reason in str(completion):
        return True
    return any(reason in str(item) for item in state.get("repair_history") or [])


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


def run_agent_eval_sync(
    *,
    suite_name: str | None = None,
    case_id: str | None = None,
    cases_root: Path = DEFAULT_AGENT_CASES_ROOT,
    work_dir: Path | None = None,
) -> AgentEvalReport:
    """同步入口，供 CLI 调用。"""
    return asyncio.run(AgentEvalRunner(cases_root=cases_root, work_dir=work_dir).run(suite_name=suite_name, case_id=case_id))
