import json

from fastapi.testclient import TestClient

from app.llm.schemas import LLMResponse
from app.schemas.approval import ApprovalSubmitResult


class ApprovalLLM:
    async def chat(self, messages, tools=None, **kwargs):
        if kwargs.get("scene") == "final_compliance":
            return LLMResponse(content="ok", has_tool_calls=False)
        return LLMResponse(
            content=None,
            tool_calls=[{"id": "call_write", "type": "function", "function": {"name": "update_policy_status", "arguments": json.dumps({"policy_no": "P123456", "status": "cancelled"})}}],
            has_tool_calls=True,
            finish_reason="tool_calls",
        )


class AcceptingApprovalClient:
    async def submit_approval_request(self, request):
        return ApprovalSubmitResult(accepted=True, external_approval_id=f"ext_{request.approval_id}", status="pending")


def test_chat_returns_pending_when_write_tool_needs_approval(app_factory):
    app = app_factory("approval_full.sqlite3")
    app.state.llm_provider.chat = ApprovalLLM().chat
    app.state.approval_service.client = AcceptingApprovalClient()
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={
            "tenant_id": "tenant",
            "channel": "web",
            "user_id": "u1",
            "session_id": "s1",
            "messages": [{"role": "user", "content": "policy_no: P123456 update status to cancelled"}],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["approval_required"] is True
    assert data["approval_status"] == "pending"
    assert data["approval_id"].startswith("approval_")
    assert data["approval_id"] in data["answer"]

    async def _read():
        return await app.state.approval_store.get(data["approval_id"])

    import anyio

    item = anyio.run(_read)
    assert item is not None
    assert item.status == "pending"
    assert item.thread_id == f"{item.session_key}:{item.request_id}"
    assert item.root_approval_id == item.approval_id
    assert item.approval_depth == 0
    assert item.tool_name == "update_policy_status"
    assert item.pending_tool_call["name"] == "update_policy_status"

    async def _logs():
        return await app.state.tool_execution_log_store.list_by_session("tenant:web:u1:s1")

    logs = anyio.run(_logs)
    assert logs[0]["tool_name"] == "update_policy_status"
    assert logs[0]["success"] is False
    assert logs[0]["error"] == "human_approval_required"
