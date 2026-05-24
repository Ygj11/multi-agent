import json

import anyio
from fastapi.testclient import TestClient

from app.llm.schemas import LLMResponse
from app.schemas.approval import ApprovalSubmitResult


class SequencedApprovalLLM:
    def __init__(self):
        self.subagent_calls = 0

    async def chat(self, messages, tools=None, **kwargs):
        if kwargs.get("scene") == "final_compliance":
            return LLMResponse(content="ok", has_tool_calls=False)
        self.subagent_calls += 1
        if self.subagent_calls == 1:
            return LLMResponse(
                content=None,
                tool_calls=[{"id": "call_write", "type": "function", "function": {"name": "update_policy_status", "arguments": json.dumps({"policy_no": "P123456", "status": "cancelled"})}}],
                has_tool_calls=True,
                finish_reason="tool_calls",
            )
        assert any(message.get("role") == "tool" for message in messages)
        return LLMResponse(content="Policy status update completed after approval.", has_tool_calls=False)


class AcceptingApprovalClient:
    async def submit_approval_request(self, request):
        return ApprovalSubmitResult(accepted=True, external_approval_id=f"ext_{request.approval_id}", status="pending")


def test_approval_callback_approved_executes_tool_and_saves_result(app_factory):
    calls = []

    async def counted_update_policy_status(policy_no=None, status=None, **kwargs):
        calls.append({"policy_no": policy_no, "status": status})
        return {"success": True, "policy_no": policy_no, "status": status}

    app = app_factory("approval_approved.sqlite3")
    app.state.tool_registry.register_private(
        agent_name="policy_query_agent",
        name="update_policy_status",
        tool=counted_update_policy_status,
        is_write=True,
    )
    app.state.llm_provider.chat = SequencedApprovalLLM().chat
    app.state.approval_service.client = AcceptingApprovalClient()
    client = TestClient(app)

    pending = client.post(
        "/api/chat",
        json={
            "tenant_id": "tenant",
            "channel": "web",
            "user_id": "u1",
            "session_id": "s1",
            "messages": [{"role": "user", "content": "policy_no: P123456 update status to cancelled"}],
        },
    ).json()
    approval_id = pending["approval_id"]
    assert calls == []

    callback = client.post(
        "/api/approval/callback",
        json={
            "approval_id": approval_id,
            "external_approval_id": f"ext_{approval_id}",
            "status": "approved",
            "approver": "manager",
            "comment": "ok",
        },
    )

    assert callback.status_code == 200
    data = callback.json()
    assert data["resumed"] is True
    assert data["status"] == "completed"
    assert data["final_answer"] == "Policy status update completed after approval."
    assert calls == [{"policy_no": "P123456", "status": "cancelled"}]

    query = client.get(f"/api/approval/{approval_id}")
    assert query.status_code == 200
    assert query.json()["status"] == "completed"
    assert query.json()["final_answer"] == "Policy status update completed after approval."

    async def _messages():
        return await app.state.message_store.list_by_session("tenant:web:u1:s1")

    messages = anyio.run(_messages)
    assert any(message["role"] == "assistant" and message["content"] == "Policy status update completed after approval." for message in messages)
