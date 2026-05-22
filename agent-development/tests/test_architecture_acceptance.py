from app.adapters.request_adapter import RequestAdapter
from app.schemas.message import ChatMessage, ChatRequest


async def test_full_architecture_acceptance_refund_failure_flow(app_factory):
    app = app_factory()
    inbound = RequestAdapter().adapt(
        ChatRequest(
            tenant_id="pingan_health",
            channel="web",
            user_id="u-accept",
            session_id="s-accept",
            messages=[ChatMessage(role="user", content="保单9201344266为什么退保没有成功")],
        )
    )

    state = await app.state.orchestrator.run(inbound)

    assert state["intent"] == "troubleshooting"
    assert state["confidence"] > 0
    assert state["entities"]["policy_no"] == "9201344266"
    assert state["available_agents"]
    assert state["selected_agent"] == "troubleshooting_agent"
    assert state["assembled_task"]["agent_name"] == "troubleshooting_agent"
    assert state["subagent_result"]["agent_name"] == "troubleshooting_agent"
    assert state["subagent_result"]["tool_calls"]
    assert state["subagent_result"]["metadata"]["tool_calling_runner"]["stopped_reason"] == "final"
    assert "query_claim_case" not in state["subagent_result"]["metadata"]["tool_calling_runner"]["visible_tools"]
    assert "query_internal_log" not in state["orchestrator_context"]["available_tools"] or "query_internal_log" in state["selected_agent_card"]["private_tools"]
    assert "final_compliance_check" in state["graph_path"]
    assert state["final_compliance_result"]["passed"] is True
    assert state["answer"] == state["final_compliance_result"]["sanitized_answer"]

    messages = await app.state.message_store.list_by_session(inbound.session_key)
    summary = await app.state.short_memory.get_summary(inbound.session_key)
    logs = await app.state.tool_execution_log_store.list_by_session(inbound.session_key)

    assert any(message["role"] == "user" for message in messages)
    assert any(message["role"] == "assistant" for message in messages)
    assert summary
    assert logs
    assert all(log["agent_name"] == "troubleshooting_agent" for log in logs)
