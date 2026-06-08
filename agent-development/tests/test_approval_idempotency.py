import json

from fastapi.testclient import TestClient

from app.llm.schemas import LLMResponse
from app.schemas.approval import ApprovalSubmitResult


class SequencedApprovalLLM:
    def __init__(self):
        self.subagent_calls = 0

    async def chat(self, messages, tools=None, **kwargs):
        if kwargs.get("scene") == "final_compliance":
            return LLMResponse(content="ok", has_tool_calls=False)
        if kwargs.get("scene") != "subagent_reasoning":
            return LLMResponse(content="memory summary", has_tool_calls=False)
        self.subagent_calls += 1
        if self.subagent_calls == 1:
            return LLMResponse(
                content=None,
                tool_calls=[
                    {
                        "id": "call_write",
                        "type": "function",
                        "function": {
                            "name": "notice_policy_update",
                            "arguments": json.dumps(
                                {"apply_seq": "APPLY123", "policyNo": "P123456", "endorseType": "001028"}
                            ),
                        },
                    }
                ],
                has_tool_calls=True,
                finish_reason="tool_calls",
            )
        return LLMResponse(content="done once", has_tool_calls=False)


class AcceptingApprovalClient:
    async def submit_approval_request(self, request):
        return ApprovalSubmitResult(accepted=True, external_approval_id=f"ext_{request.approval_id}", status="pending")


def test_approval_callback_is_idempotent(app_factory):
    calls = []

    async def counted_notice_policy_update(apply_seq=None, policyNo=None, endorseType=None, **kwargs):
        calls.append({"apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType})
        return {"success": True}

    app = app_factory("approval_idempotent.sqlite3")
    app.state.tool_registry.register_private(
        agent_name="troubleshooting_agent",
        name="notice_policy_update",
        tool=counted_notice_policy_update,
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
            "messages": [{"role": "user", "content": "APPLY123 保单号 P123456 endorseType 001028 保单更新失败，请通知保单更新"}],
        },
    ).json()

    payload = {
        "approval_id": pending["approval_id"],
        "external_approval_id": f"ext_{pending['approval_id']}",
        "status": "approved",
    }
    first = client.post("/api/approval/callback", json=payload)
    second = client.post("/api/approval/callback", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == [{"apply_seq": "APPLY123", "policyNo": "P123456", "endorseType": "001028"}]
    assert second.json()["status"] == "completed"
    assert second.json()["final_answer"] == "done once"
