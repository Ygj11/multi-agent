from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.runtime.orchestrator import AgentOrchestrator
from app.runtime.session_locks import SessionExecutionLockManager
from app.schemas.approval import ApprovalRequest
from app.schemas.message import ChatMessage, InboundMessage


class RecordingGraph:
    def __init__(self, *, delay: float = 0.03) -> None:
        self.delay = delay
        self.active_by_session: dict[str, int] = {}
        self.max_active_by_session: dict[str, int] = {}
        self.started: list[str] = []

    async def ainvoke(self, state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        session_key = state["session_key"]
        self.started.append(str(state["request_id"]))
        self.active_by_session[session_key] = self.active_by_session.get(session_key, 0) + 1
        self.max_active_by_session[session_key] = max(
            self.max_active_by_session.get(session_key, 0),
            self.active_by_session[session_key],
        )
        await asyncio.sleep(self.delay)
        self.active_by_session[session_key] -= 1
        return {
            **state,
            "answer": f"ok:{state['request_id']}",
            "rewritten_query": state.get("original_query", ""),
            "intent": "unknown",
            "graph_path": [*state.get("graph_path", []), "fake_graph"],
        }


def _inbound(request_id: str, *, session_key: str = "tenant:web:u1:s1") -> InboundMessage:
    return InboundMessage(
        request_id=request_id,
        trace_id=f"trace_{request_id}",
        tenant_id="tenant",
        channel="web",
        user_id="u1",
        session_id="s1",
        session_key=session_key,
        original_query="hello",
        messages=[ChatMessage(role="user", content="hello")],
    )


def _resume_state(request_id: str, *, session_key: str = "tenant:web:u1:s1") -> dict[str, Any]:
    return {
        "request_id": request_id,
        "trace_id": f"trace_{request_id}",
        "tenant_id": "tenant",
        "channel": "web",
        "user_id": "u1",
        "session_id": "s1",
        "session_key": session_key,
        "thread_id": f"{session_key}:{request_id}",
        "original_query": "resume",
    }


@pytest.mark.asyncio
async def test_orchestrator_serializes_same_session_requests():
    graph = RecordingGraph()
    orchestrator = AgentOrchestrator(
        graph,
        session_locks=SessionExecutionLockManager(timeout_seconds=1),
    )

    await asyncio.gather(orchestrator.run(_inbound("req1")), orchestrator.run(_inbound("req2")))

    assert graph.max_active_by_session["tenant:web:u1:s1"] == 1


@pytest.mark.asyncio
async def test_orchestrator_allows_different_sessions_concurrently():
    graph = RecordingGraph()
    orchestrator = AgentOrchestrator(
        graph,
        session_locks=SessionExecutionLockManager(timeout_seconds=1),
    )

    await asyncio.gather(
        orchestrator.run(_inbound("req1", session_key="tenant:web:u1:s1")),
        orchestrator.run(_inbound("req2", session_key="tenant:web:u2:s1")),
    )

    assert graph.max_active_by_session["tenant:web:u1:s1"] == 1
    assert graph.max_active_by_session["tenant:web:u2:s1"] == 1
    assert set(graph.started) == {"req1", "req2"}


@pytest.mark.asyncio
async def test_orchestrator_serializes_approval_resume_with_same_session_request():
    graph = RecordingGraph()
    orchestrator = AgentOrchestrator(
        graph,
        session_locks=SessionExecutionLockManager(timeout_seconds=1),
    )
    approval = ApprovalRequest(
        approval_id="appr1",
        request_id="req_approval",
        session_key="tenant:web:u1:s1",
        thread_id="tenant:web:u1:s1:req_approval",
        agent_name="troubleshooting_agent",
        tool_name="policy_suspendOrRecovery",
        reason="test",
        resume_state=_resume_state("req_approval"),
    )

    await asyncio.gather(orchestrator.run(_inbound("req1")), orchestrator.resume_after_approval(approval))

    assert graph.max_active_by_session["tenant:web:u1:s1"] == 1
