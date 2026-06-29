from __future__ import annotations

from app.adapters.request_adapter import RequestAdapter
from app.runtime.handlers.task_completion_handler import TaskCompletionGraphHandler
from app.schemas.message import ChatMessage, ChatRequest
from app.verification.task_completion.schemas import (
    RepairPlan,
    TaskCompletionVerificationContext,
    TaskCompletionVerificationResult,
    VerificationEvidence,
)


def _pos_request(session_id: str = "s-task-completion") -> ChatRequest:
    return ChatRequest(
        tenant_id="pingan_health",
        channel="web",
        user_id="u001",
        session_id=session_id,
        messages=[ChatMessage(role="user", content="查询保单 9201344266 可以做哪些保全项，customerNo C001。")],
    )


async def test_task_completion_verify_passes_with_successful_tool_evidence(app_factory):
    app = app_factory("task-completion-pass.sqlite3")
    inbound = RequestAdapter().adapt(_pos_request())

    state = await app.state.container.orchestrator.run(inbound)

    assert state["selected_skill_id"] == "pos_query_agent.realtime_query"
    assert "collect_verification_evidence" in state["graph_path"]
    assert "verify_task_completion" in state["graph_path"]
    assert "dispatch_repair_agent" not in state["graph_path"]
    assert state["task_completion_verification_result"]["status"] == "PASS"
    assert state["task_completion_verification_result"]["completed"] is True


async def test_task_completion_continue_repairs_with_same_agent_and_pinned_skill(app_factory):
    app = app_factory("task-completion-repair.sqlite3")
    contexts = []

    class SequenceVerifier:
        async def verify(self, context):
            contexts.append(context)
            if len(contexts) == 1:
                return TaskCompletionVerificationResult(
                    status="CONTINUE",
                    completed=False,
                    summary="首轮缺少补充核查。",
                    completed_items=["已完成首次查询"],
                    missing_items=["需要继续核查"],
                    repair_plan=RepairPlan(
                        reason="继续完成缺失核查",
                        completed_items=["已完成首次查询"],
                        missing_items=["需要继续核查"],
                        next_steps=["继续按原 Skill 核查"],
                        do_not_repeat=["不要更换 Agent 或 Skill"],
                        reuse_evidence_ids=[],
                        expected_new_evidence=["repair_tool_result"],
                        target_agent=context.selected_agent,
                        selected_skill_id=context.selected_skill_id,
                        confidence=0.9,
                    ),
                    confidence=0.9,
                    reasoning_summary="fake_continue",
                    evidence_ids=[],
                    verifier_name="fake_sequence",
                )
            return TaskCompletionVerificationResult(
                status="PASS",
                completed=True,
                summary="修复轮次完成。",
                completed_items=["repair 完成"],
                missing_items=[],
                repair_plan=None,
                confidence=0.9,
                reasoning_summary="fake_pass",
                evidence_ids=[],
                verifier_name="fake_sequence",
            )

    app.state.container.task_completion_handler.verifier_service = SequenceVerifier()
    inbound = RequestAdapter().adapt(_pos_request(session_id="s-task-completion-repair"))

    state = await app.state.container.orchestrator.run(inbound)

    assert len(contexts) == 2
    assert {context.selected_agent for context in contexts} == {"pos_query_agent"}
    assert {context.selected_skill_id for context in contexts} == {"pos_query_agent.realtime_query"}
    assert contexts[1].repair_round == 1
    assert "dispatch_repair_agent" in state["graph_path"]
    assert state["execution_mode"] == "repair"
    assert state["repair_round"] == 1
    assert state["selected_skill_id"] == "pos_query_agent.realtime_query"
    assert state["task_completion_verification_result"]["status"] == "PASS"


def test_task_completion_schema_requires_repair_plan_for_continue():
    try:
        TaskCompletionVerificationResult(
            status="CONTINUE",
            completed=False,
            summary="need continue",
            completed_items=[],
            missing_items=["x"],
            repair_plan=None,
            confidence=0.8,
            reasoning_summary="missing repair plan",
        )
    except ValueError as exc:
        assert "repair_plan" in str(exc)
    else:
        raise AssertionError("CONTINUE without repair_plan should fail")


async def test_verify_task_completion_reuses_collected_context_by_default():
    class Collector:
        def __init__(self):
            self.calls = 0

        async def collect(self, state):
            self.calls += 1
            return (
                TaskCompletionVerificationContext(
                    session_key="s001",
                    original_query="原始问题",
                    rewritten_query="改写问题",
                    selected_agent="pos_query_agent",
                    selected_skill_id="pos_query_agent.realtime_query",
                    skill_content="SOP",
                    answer="answer",
                    evidence=[
                        VerificationEvidence(
                            evidence_id=f"ev-{self.calls}",
                            source_type="tool",
                            source_name="mock",
                            summary=f"evidence-{self.calls}",
                        )
                    ],
                ),
                f"v{self.calls}",
            )

    class Verifier:
        def __init__(self):
            self.contexts = []

        async def verify(self, context):
            self.contexts.append(context)
            return TaskCompletionVerificationResult(
                status="PASS",
                completed=True,
                summary=context.evidence[0].summary,
                confidence=0.9,
            )

    collector = Collector()
    verifier = Verifier()
    handler = TaskCompletionGraphHandler(evidence_collector=collector, verifier_service=verifier)
    state = {
        "selected_skill_id": "pos_query_agent.realtime_query",
        "subagent_result": {"answer": "answer"},
        "repair_history": [],
    }

    collected = await handler.collect_verification_evidence(state)
    state.update(collected)
    verified = await handler.verify_task_completion(state)

    assert collector.calls == 1
    assert verifier.contexts[0].evidence[0].summary == "evidence-1"
    assert verified["selected_skill_version"] == "v1"


async def test_verify_task_completion_refreshes_evidence_when_explicitly_enabled():
    class Collector:
        def __init__(self):
            self.calls = 0

        async def collect(self, state):
            self.calls += 1
            return (
                TaskCompletionVerificationContext(
                    session_key="s001",
                    original_query="原始问题",
                    rewritten_query="改写问题",
                    selected_agent="pos_query_agent",
                    selected_skill_id="pos_query_agent.realtime_query",
                    skill_content="SOP",
                    answer="answer",
                    evidence=[
                        VerificationEvidence(
                            evidence_id=f"ev-{self.calls}",
                            source_type="tool",
                            source_name="mock",
                            summary=f"evidence-{self.calls}",
                        )
                    ],
                ),
                f"v{self.calls}",
            )

    class Verifier:
        def __init__(self):
            self.contexts = []

        async def verify(self, context):
            self.contexts.append(context)
            return TaskCompletionVerificationResult(
                status="PASS",
                completed=True,
                summary=context.evidence[0].summary,
                confidence=0.9,
            )

    collector = Collector()
    verifier = Verifier()
    handler = TaskCompletionGraphHandler(
        evidence_collector=collector,
        verifier_service=verifier,
        refresh_evidence_before_verify=True,
    )
    state = {
        "selected_skill_id": "pos_query_agent.realtime_query",
        "subagent_result": {"answer": "answer"},
        "repair_history": [],
    }

    collected = await handler.collect_verification_evidence(state)
    state.update(collected)
    verified = await handler.verify_task_completion(state)

    assert collector.calls == 2
    assert verifier.contexts[0].evidence[0].summary == "evidence-2"
    assert verified["selected_skill_version"] == "v2"
