"""TroubleshootingAgent 无 skill 执行边界测试。"""

from app.adapters.request_adapter import RequestAdapter
from app.schemas.message import ChatMessage, ChatRequest


async def test_graph_final_state_blocks_tool_loop_without_skill(app_factory):
    """graph final state 在无匹配 skill 时不应构造伪 evidence。"""
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

    state = await app.state.container.orchestrator.run(inbound)
    subagent_result = state["subagent_result"]

    assert subagent_result["selected_skill_id"] is None
    assert subagent_result["metadata"]["no_skill_blocked"] is True
    assert subagent_result["evidence"] == []
    assert subagent_result["tool_calls"] == []
    assert subagent_result["diagnosis"] is None
    assert subagent_result["recommendation"] is None
    assert subagent_result["responsibility"] is None
