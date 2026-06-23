import json

import anyio
from fastapi.testclient import TestClient

from app.adapters.request_adapter import RequestAdapter
from app.llm.schemas import LLMResponse
from app.schemas.approval import ApprovalSubmitResult
from app.schemas.message import ChatMessage, ChatRequest


TOP_LEVEL_CACHE_FIELDS = {
    "selected_skill_id",
    "selected_skill_metadata",
    "skill_selection_score",
    "skill_selection_reason",
    "approval_request",
}
CHECKPOINT_FORBIDDEN_CACHE_FIELDS = {
    "selected_skill_metadata",
    "skill_selection_score",
    "skill_selection_reason",
    "approval_request",
}


class WriteApprovalLLM:
    async def chat(self, messages, tools=None, **kwargs):
        if kwargs.get("scene") == "final_compliance":
            return LLMResponse(content="ok", has_tool_calls=False)
        return LLMResponse(
            content=None,
            tool_calls=[
                {
                    "id": "call_write",
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


class AcceptingApprovalClient:
    async def submit_approval_request(self, request):
        return ApprovalSubmitResult(accepted=True, external_approval_id=f"ext_{request.approval_id}", status="pending")


async def test_normal_graph_state_has_no_top_level_selected_skill_cache(app_factory):
    app = app_factory("no-selected-skill-cache.sqlite3")
    inbound = RequestAdapter().adapt(
        ChatRequest(
            tenant_id="pingan_health",
            channel="web",
            user_id="u001",
            session_id="s001",
            messages=[ChatMessage(role="user", content="REQ_001 为什么返回 E102？")],
        )
    )

    state = await app.state.container.orchestrator.run(inbound)

    for field in TOP_LEVEL_CACHE_FIELDS:
        assert field not in state
    assert state["subagent_result"]["selected_skill_id"] is None


def test_pending_approval_checkpoint_has_no_top_level_approval_request(app_factory, real_troubleshooting_env):
    app = app_factory("no-approval-request-cache.sqlite3")
    app.state.container.llm_provider.chat = WriteApprovalLLM().chat
    app.state.container.approval_service.client = AcceptingApprovalClient()
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={
            "tenant_id": "tenant",
            "channel": "web",
            "user_id": "u1",
            "session_id": "s1",
            "messages": [{"role": "user", "content": "930010412672222 保单号 9200100000458846 endorseType 001028 保单更新失败，请通知保单更新"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    thread_id = f"{payload['session_key']}:{payload['request_id']}"
    state = anyio.run(app.state.container.storage.checkpoint_store.load, thread_id)

    assert state is not None
    for field in CHECKPOINT_FORBIDDEN_CACHE_FIELDS:
        assert field not in state
    assert state["selected_skill_id"] == "troubleshooting_agent.endo_completion_aftercare"
    assert state["approval_id"] == payload["approval_id"]
    assert state["approval_status"] == "pending"
