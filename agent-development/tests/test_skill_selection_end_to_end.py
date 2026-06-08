from app.adapters.request_adapter import RequestAdapter
from app.schemas.message import ChatMessage, ChatRequest


async def test_troubleshooting_req_001_selects_signature_error_skill(app_factory):
    """REQ_001 端到端应选择 troubleshooting_agent.signature_error。"""
    app = app_factory("skill-e2e.sqlite3")
    inbound = RequestAdapter().adapt(
        ChatRequest(
            tenant_id="pingan_health",
            channel="web",
            user_id="u001",
            session_id="s001",
            messages=[ChatMessage(role="user", content="REQ_001 为什么返回 E102？")],
        )
    )

    state = await app.state.orchestrator.run(inbound)

    assert state["intent"] == "troubleshooting"
    assert state["subagent_result"]["selected_skill_id"] == "troubleshooting_agent.signature_error"
    assert "E102" in state["answer"]


async def test_pos_query_selects_realtime_query_skill(app_factory):
    """保全实时查询应选择 pos_query_agent.realtime_query。"""
    app = app_factory("skill-change.sqlite3")
    inbound = RequestAdapter().adapt(
        ChatRequest(
            tenant_id="pingan_health",
            channel="web",
            user_id="u001",
            session_id="s-change",
            messages=[
                ChatMessage(
                    role="user",
                    content="查询保单 9201344266 可以做哪些保全项，customerNo C001。",
                )
            ],
        )
    )

    state = await app.state.orchestrator.run(inbound)

    assert state["intent"] == "pos_query"
    assert state["subagent_result"]["selected_skill_id"] == "pos_query_agent.realtime_query"
