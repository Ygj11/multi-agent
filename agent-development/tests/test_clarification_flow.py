from app.adapters.request_adapter import RequestAdapter
from app.schemas.message import ChatMessage, ChatRequest


async def test_clarification_skips_dispatch_and_is_saved(app_factory):
    app = app_factory("clarification.sqlite3")
    inbound = RequestAdapter().adapt(
        ChatRequest(
            tenant_id="tenant",
            channel="web",
            user_id="user",
            session_id="clarify",
            messages=[ChatMessage(role="user", content="继续看一下")],
        )
    )

    state = await app.state.orchestrator.run(inbound)

    assert "build_clarification_answer" in state["graph_path"]
    assert "dispatch_agent" not in state["graph_path"]
    assert "pre_answer_verify" in state["graph_path"]
    messages = await app.state.message_store.list_by_session(state["session_key"], limit=5)
    assert any(message["role"] == "assistant" and state["answer"] in message["content"] for message in messages)
