"""TroubleshootingAgent 结构化 evidence 测试。"""

from app.adapters.request_adapter import RequestAdapter
from app.schemas.message import ChatMessage, ChatRequest


async def test_graph_final_state_contains_structured_evidence(app_factory):
    """graph final state 的 subagent_result 应包含结构化 evidence。"""
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
    subagent_result = state["subagent_result"]
    evidence = subagent_result["evidence"]

    assert subagent_result["diagnosis"]
    assert subagent_result["recommendation"]
    assert subagent_result["responsibility"]
    assert {item["type"] for item in evidence} >= {"internal_log", "knowledge"}
    for item in evidence:
        assert {"type", "source", "tool_name", "summary", "confidence"}.issubset(item)
        assert "result_preview" in item or "raw_ref" in item
