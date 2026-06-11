import json

from fastapi.testclient import TestClient

from app.llm.schemas import LLMResponse
from app.schemas.approval import ApprovalSubmitResult


class ChainedWriteLLM:
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
                        "id": "call_write_a",
                        "type": "function",
                        "function": {
                            "name": "notice_policy_update",
                            "arguments": json.dumps(
                                {"apply_seq": "930010412672222", "policyNo": "9200100000458846", "endorseType": "001028"}
                            ),
                        },
                    }
                ],
                has_tool_calls=True,
                finish_reason="tool_calls",
            )
        if self.subagent_calls == 2:
            assert any(message.get("role") == "tool" and message.get("name") == "notice_policy_update" for message in messages)
            return LLMResponse(
                content=None,
                tool_calls=[
                    {
                        "id": "call_write_b",
                        "type": "function",
                        "function": {
                            "name": "notice_policy_update",
                            "arguments": json.dumps(
                                {"apply_seq": "930010412672223", "policyNo": "9200100000458846", "endorseType": "001028"}
                            ),
                        },
                    }
                ],
                has_tool_calls=True,
                finish_reason="tool_calls",
            )
        assert any("930010412672223" in str(message.get("content")) for message in messages if message.get("role") == "tool")
        return LLMResponse(content="Both approved writes completed.", has_tool_calls=False)


class ManyWritesLLM:
    def __init__(self):
        self.subagent_calls = 0

    async def chat(self, messages, tools=None, **kwargs):
        if kwargs.get("scene") == "final_compliance":
            return LLMResponse(content="ok", has_tool_calls=False)
        if kwargs.get("scene") != "subagent_reasoning":
            return LLMResponse(content="memory summary", has_tool_calls=False)

        status = f"status_{self.subagent_calls}"
        self.subagent_calls += 1
        return LLMResponse(
            content=None,
            tool_calls=[
                {
                    "id": f"call_write_{status}",
                    "type": "function",
                    "function": {
                        "name": "notice_policy_update",
                        "arguments": json.dumps(
                            {"apply_seq": f"APPLY{self.subagent_calls}", "policyNo": "9200100000458846", "endorseType": status}
                        ),
                    },
                }
            ],
            has_tool_calls=True,
            finish_reason="tool_calls",
        )


class AcceptingApprovalClient:
    async def submit_approval_request(self, request):
        return ApprovalSubmitResult(accepted=True, external_approval_id=f"ext_{request.approval_id}", status="pending")


def test_approval_resume_creates_second_approval_in_graph(app_factory, real_troubleshooting_env):
    calls = []

    async def counted_notice_policy_update(apply_seq=None, policyNo=None, endorseType=None, **kwargs):
        calls.append({"apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType})
        return {"success": True, "apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType}

    app = app_factory("approval_chain.sqlite3")
    app.state.tool_registry.register_private(
        agent_name="troubleshooting_agent",
        name="notice_policy_update",
        tool=counted_notice_policy_update,
        is_write=True,
    )
    app.state.llm_provider.chat = ChainedWriteLLM().chat
    app.state.approval_service.client = AcceptingApprovalClient()
    client = TestClient(app)

    pending_1 = client.post(
        "/api/chat",
        json={
            "tenant_id": "tenant",
            "channel": "web",
            "user_id": "u1",
            "session_id": "s1",
            "messages": [{"role": "user", "content": "930010412672222 保单号 9200100000458846 endorseType 001028 保单更新失败，请连续通知保单更新"}],
        },
    ).json()
    approval_1_id = pending_1["approval_id"]
    assert calls == []

    callback_1 = client.post(
        "/api/approval/callback",
        json={
            "approval_id": approval_1_id,
            "external_approval_id": f"ext_{approval_1_id}",
            "status": "approved",
            "approver": "manager",
        },
    )
    assert callback_1.status_code == 200
    data_1 = callback_1.json()
    assert data_1["status"] == "completed"
    assert calls == [{"apply_seq": "930010412672222", "policyNo": "9200100000458846", "endorseType": "001028"}]

    async def _get(approval_id):
        return await app.state.approval_store.get(approval_id)

    import anyio

    approval_1 = anyio.run(_get, approval_1_id)
    assert approval_1.next_approval_id
    approval_2_id = approval_1.next_approval_id
    approval_2 = anyio.run(_get, approval_2_id)
    assert approval_2.status == "pending"
    assert approval_2.parent_approval_id == approval_1_id
    assert approval_2.root_approval_id == approval_1.root_approval_id
    assert approval_2.approval_depth == approval_1.approval_depth + 1
    assert approval_2.pending_tool_call["name"] == "notice_policy_update"
    assert approval_2.arguments == {"apply_seq": "930010412672223", "policyNo": "9200100000458846", "endorseType": "001028"}
    assert "resume_approved_tool" in (approval_1.result or {}).get("graph_path", [])

    callback_2 = client.post(
        "/api/approval/callback",
        json={
            "approval_id": approval_2_id,
            "external_approval_id": f"ext_{approval_2_id}",
            "status": "approved",
            "approver": "manager",
        },
    )
    assert callback_2.status_code == 200
    data_2 = callback_2.json()
    assert data_2["status"] == "completed"
    assert data_2["final_answer"] == "Both approved writes completed."
    assert calls == [
        {"apply_seq": "930010412672222", "policyNo": "9200100000458846", "endorseType": "001028"},
        {"apply_seq": "930010412672223", "policyNo": "9200100000458846", "endorseType": "001028"},
    ]


def test_approval_chain_depth_limit_requires_manual_intervention(app_factory, real_troubleshooting_env):
    calls = []

    async def counted_notice_policy_update(apply_seq=None, policyNo=None, endorseType=None, **kwargs):
        calls.append({"apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType})
        return {"success": True, "apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType}

    app = app_factory("approval_chain_limit.sqlite3")
    app.state.tool_registry.register_private(
        agent_name="troubleshooting_agent",
        name="notice_policy_update",
        tool=counted_notice_policy_update,
        is_write=True,
    )
    app.state.llm_provider.chat = ManyWritesLLM().chat
    app.state.approval_service.client = AcceptingApprovalClient()
    client = TestClient(app)

    pending = client.post(
        "/api/chat",
        json={
            "tenant_id": "tenant",
            "channel": "web",
            "user_id": "u1",
            "session_id": "s2",
            "messages": [{"role": "user", "content": "930010412672222 保单号 9200100000458846 endorseType 001028 保单更新失败，请多次通知保单更新"}],
        },
    ).json()

    import anyio

    async def _get(approval_id):
        return await app.state.approval_store.get(approval_id)

    approval_id = pending["approval_id"]
    final_status = None
    for _ in range(5):
        response = client.post(
            "/api/approval/callback",
            json={
                "approval_id": approval_id,
                "external_approval_id": f"ext_{approval_id}",
                "status": "approved",
                "approver": "manager",
            },
        )
        assert response.status_code == 200
        item = anyio.run(_get, approval_id)
        final_status = item.status
        if item.next_approval_id:
            approval_id = item.next_approval_id
            continue
        break

    assert final_status == "manual_intervention_required"
    assert len(calls) == 3
    assert calls[-1]["endorseType"] == "status_2"
