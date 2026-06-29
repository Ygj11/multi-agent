from __future__ import annotations

from typing import Any

import pytest

from app.adapters.request_adapter import RequestAdapter
from app.approval.service import ApprovalService
from app.schemas.approval import ApprovalCallbackRequest, ApprovalRequest
from app.schemas.message import ChatMessage, ChatRequest


class FakeApprovalStore:
    def __init__(self, request: ApprovalRequest) -> None:
        self.request = request
        self.events: list[tuple[str | None, dict[str, Any] | None]] = []

    async def get(self, approval_id: str) -> ApprovalRequest | None:
        return self.request if approval_id == self.request.approval_id else None

    async def update(
        self,
        request: ApprovalRequest,
        event_type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        self.request = request
        self.events.append((event_type, payload))
        return request


class FakeOrchestrator:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    async def resume_after_approval(self, approval_request: ApprovalRequest) -> dict[str, Any]:
        return self.state


class CapturingApprovalService(ApprovalService):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.result_callbacks: list[tuple[str, dict[str, Any]]] = []

    async def _post_result_callback(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.result_callbacks.append((url, payload))
        return {"status_code": 200}


def _approval_request(*, callback_url: str | None = "https://caller.example.test/final") -> ApprovalRequest:
    resume_state: dict[str, Any] = {
        "schema_version": 1,
        "request_id": "req_1",
        "trace_id": "trace_1",
        "session_key": "tenant:web:u1:s1",
        "thread_id": "tenant:web:u1:s1:req_1",
        "original_query": "请通知保单更新",
    }
    if callback_url:
        resume_state["result_callback_url"] = callback_url
    return ApprovalRequest(
        approval_id="approval_1",
        request_id="req_1",
        trace_id="trace_1",
        session_key="tenant:web:u1:s1",
        thread_id="tenant:web:u1:s1:req_1",
        agent_name="troubleshooting_agent",
        tool_name="notice_policy_update",
        reason="write tool requires approval",
        status="pending",
        resume_state=resume_state,
        pending_state=resume_state,
    )


def _service(request: ApprovalRequest, *, state: dict[str, Any]) -> CapturingApprovalService:
    return CapturingApprovalService(
        store=FakeApprovalStore(request),
        client=object(),
        verification_service=object(),
        message_store=object(),
        short_memory=object(),
        callback_url="http://localhost:8000/api/approval/callback",
        orchestrator=FakeOrchestrator(state),
    )


def test_chat_request_result_callback_url_flows_into_inbound_message():
    request = ChatRequest(
        tenant_id="tenant",
        channel="web",
        user_id="u1",
        session_id="s1",
        messages=[ChatMessage(role="user", content="请通知保单更新")],
        result_callback_url="https://caller.example.test/final",
    )

    inbound = RequestAdapter().adapt(request)

    assert inbound.result_callback_url == "https://caller.example.test/final"


@pytest.mark.asyncio
async def test_approval_result_callback_posts_terminal_answer_after_resume():
    request = _approval_request()
    service = _service(
        request,
        state={
            "answer": "最终处理完成。",
            "approval_required": False,
            "approval_id": "approval_1",
            "graph_path": ["route_entry", "resume_approved_tool", "finalize_response"],
        },
    )

    result = await service.handle_callback(
        ApprovalCallbackRequest(
            approval_id="approval_1",
            status="approved",
            approver="manager",
        )
    )

    assert result.final_answer == "最终处理完成。"
    assert service.result_callbacks == [
        (
            "https://caller.example.test/final",
            {
                "event": "approval_final_result",
                "approval_id": "approval_1",
                "root_approval_id": "approval_1",
                "parent_approval_id": None,
                "request_id": "req_1",
                "trace_id": "trace_1",
                "session_key": "tenant:web:u1:s1",
                "status": "completed",
                "final_answer": "最终处理完成。",
                "error": None,
                "graph_path": ["route_entry", "resume_approved_tool", "finalize_response"],
                "created_at": request.created_at,
                "decided_at": request.decided_at,
            },
        )
    ]
    assert request.result is not None
    assert request.result["result_callback"]["delivered"] is True
    assert ("result_callback_delivered", request.result["result_callback"]) in service.store.events


@pytest.mark.asyncio
async def test_approval_result_callback_skips_middle_of_approval_chain():
    request = _approval_request()
    service = _service(
        request,
        state={
            "answer": "还有下一次写工具需要审批。",
            "approval_required": True,
            "approval_id": "approval_2",
            "graph_path": ["route_entry", "resume_approved_tool", "create_approval_request"],
        },
    )

    result = await service.handle_callback(
        ApprovalCallbackRequest(
            approval_id="approval_1",
            status="approved",
            approver="manager",
        )
    )

    assert result.final_answer == "还有下一次写工具需要审批。"
    assert service.result_callbacks == []
    assert request.next_approval_id == "approval_2"
    assert any(event_type == "completed_with_next_approval" for event_type, _ in service.store.events)
