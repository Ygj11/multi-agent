"""LangGraph 真实状态机流转验收测试。"""

from app.adapters.request_adapter import RequestAdapter
from app.schemas.message import ChatMessage, ChatRequest


async def test_langgraph_flow_routes_to_troubleshooting(app_factory):
    """troubleshooting 意图应经过 route_intent 并进入子 Agent 分支。"""
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
    assert "route_intent" in state["graph_path"]
    assert "call_troubleshooting_agent" in state["graph_path"]
    assert "direct_answer" not in state["graph_path"]
    assert state["graph_path"][-1] == "finalize_response"
