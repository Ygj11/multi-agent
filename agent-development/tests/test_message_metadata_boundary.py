from app.adapters.request_adapter import RequestAdapter
from app.schemas.message import ChatMessage, ChatRequest


async def test_assistant_message_metadata_keeps_business_summary_not_debug_traces(app_factory):
    app = app_factory()
    inbound = RequestAdapter().adapt(
        ChatRequest(
            tenant_id="pingan_health",
            channel="web",
            user_id="u-message-boundary",
            session_id="s-message-boundary",
            messages=[ChatMessage(role="user", content="保单9200100000458846为什么退保没有成功？")],
        )
    )

    await app.state.orchestrator.run(inbound)
    messages = await app.state.message_store.list_by_session(inbound.session_key)
    assistant = next(message for message in reversed(messages) if message["role"] == "assistant")
    metadata = assistant["metadata"]

    assert metadata["selected_agent"] == "troubleshooting_agent"
    assert metadata["selected_skill_id"] == "troubleshooting_agent.refund_failure"
    assert metadata["entities"]["policy_no"] == "9200100000458846"
    assert "fallback_summary" in metadata
    assert "decision_traces" not in metadata
    assert "selected_skill_metadata" not in metadata
    assert "tool_calling_runner" not in metadata
    assert "pending_messages" not in metadata
    assert "pending_tools" not in metadata
