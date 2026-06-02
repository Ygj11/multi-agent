"""LangGraph task-level orchestration flow tests."""

from app.adapters.request_adapter import RequestAdapter
from app.schemas.message import ChatMessage, ChatRequest


async def test_langgraph_flow_selects_and_dispatches_troubleshooting_agent(app_factory):
    app = app_factory()
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
    assert state["entities"]["request_id"] == "REQ_001"
    assert state["selected_agent"] == "troubleshooting_agent"
    assert "discover_agents" in state["graph_path"]
    assert "select_agent" in state["graph_path"]
    assert "assemble_task" in state["graph_path"]
    assert "dispatch_agent" in state["graph_path"]
    assert "pre_answer_verify" in state["graph_path"]
    assert "route_intent" not in state["graph_path"]
    assert "call_troubleshooting_agent" not in state["graph_path"]
    assert state["graph_path"][-1] == "finalize_response"
