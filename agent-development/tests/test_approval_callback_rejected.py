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


def test_approval_callback_rejected_does_not_execute_tool(app_factory):
    calls = []

    async def counted_update_policy_status(policy_no=None, status=None, **kwargs):
        calls.append({"policy_no": policy_no, "status": status})
        return {"success": True}

    app = app_factory("approval_rejected.sqlite3")
    app.state.tool_registry.register_private(
        agent_name="policy_query_agent",
        name="update_policy_status",
        tool=counted_update_policy_status,
        is_write=True,
    )
    app.state.llm_provider.chat = ApprovalLLM().chat
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

    callback = client.post(
        "/api/approval/callback",
        json={
            "approval_id": pending["approval_id"],
            "external_approval_id": f"ext_{pending['approval_id']}",
            "status": "rejected",
            "approver": "manager",
            "comment": "no",
        },
    )

    assert callback.status_code == 200
    data = callback.json()
    assert data["status"] == "rejected"
    assert data["final_answer"] == "审批未通过，相关操作未执行。"
    assert calls == []

    query = client.get(f"/api/approval/{pending['approval_id']}")
    assert query.json()["status"] == "rejected"
    assert query.json()["final_answer"] == "审批未通过，相关操作未执行。"
