from app.adapters.request_adapter import RequestAdapter
from app.schemas.message import ChatMessage, ChatRequest


async def test_runtime_state_omits_large_routing_objects(app_factory):
    app = app_factory()
    inbound = RequestAdapter().adapt(
        ChatRequest(
            tenant_id="pingan_health",
            channel="web",
            user_id="u-state-slim",
            session_id="s-state-slim",
            messages=[ChatMessage(role="user", content="保单9200100000458846为什么退保没有成功？")],
        )
    )

    state = await app.state.orchestrator.run(inbound)

    forbidden = {
        "available_agents",
        "selected_agent_card",
        "assembled_task",
        "verification_results",
    }
    assert forbidden.isdisjoint(state)
    assert "discover_agents" not in state["graph_path"]
    assert "assemble_task" not in state["graph_path"]
    assert state["agent_selection_summary"]["selected_agent"] == "troubleshooting_agent"
    assert set(state["agent_selection_summary"]) == {
        "selected_agent",
        "confidence",
        "selection_method",
        "fallback_used",
        "fallback_reason",
        "candidate_count",
        "llm_status",
    }
    assert "candidates" not in state["agent_selection_summary"]
    assert "card" not in state["agent_selection_summary"]
