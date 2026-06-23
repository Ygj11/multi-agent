"""多轮对话短期记忆验收测试。"""

from app.adapters.request_adapter import RequestAdapter
from app.schemas.message import ChatMessage, ChatRequest


def _chat_request(content: str, *, session_id: str = "s001") -> ChatRequest:
    return ChatRequest(
        tenant_id="pingan_health",
        channel="web",
        user_id="u001",
        session_id=session_id,
        messages=[ChatMessage(role="user", content=content)],
    )


def test_second_turn_uses_first_turn_context(client):
    """第二轮追问应能复用第一轮 E102 上下文，但无 skill 时仍不执行泛化诊断。"""
    payload = {
        "tenant_id": "pingan_health",
        "channel": "web",
        "user_id": "u001",
        "session_id": "s001",
        "messages": [{"role": "user", "content": "REQ_001 为什么返回 E102？"}],
    }
    first = client.post("/api/chat", json=payload)
    assert first.status_code == 200

    second = client.post(
        "/api/chat",
        json={
            "tenant_id": "pingan_health",
            "channel": "web",
            "user_id": "u001",
            "session_id": "s001",
            "messages": [{"role": "user", "content": "那这个一般是谁的问题？"}],
        },
    )

    assert second.status_code == 200
    data = second.json()
    assert data["intent"] == "troubleshooting"
    assert "上一轮" in data["rewritten_query"]
    assert "REQ_001" in data["rewritten_query"]
    assert "E102" in data["rewritten_query"]
    assert "没有匹配到可执行的业务技能" in data["answer"]


async def test_clarification_reply_inherits_pending_task_entities(app_factory):
    """上一轮 skill 澄清缺实体后，下一轮补参应恢复原任务上下文。"""
    app = app_factory("clarification-reply.sqlite3")
    adapter = RequestAdapter()

    first_state = await app.state.container.orchestrator.run(
        adapter.adapt(
            _chat_request(
                "保全任务完成，受理号930010412672222，保单9200100000458846没有更新？",
                session_id="s-clarify",
            )
        )
    )

    assert first_state["intent"] == "troubleshooting"
    assert first_state["sub_intent"] == "endo_completion_aftercare"
    assert first_state["need_clarification"] is True
    assert first_state["missing_required_entities"] == ["endorseType"]
    assert first_state["entities"] == {
        "apply_seq": "930010412672222",
        "policy_no": "9200100000458846",
    }
    assert first_state["subagent_result"]["selected_skill_id"] == "troubleshooting_agent.endo_completion_aftercare"

    first_messages = await app.state.container.storage.message_store.list_by_session(first_state["session_key"])
    first_assistant_metadata = first_messages[-1]["metadata"]
    assert first_assistant_metadata["need_clarification"] is True
    assert first_assistant_metadata["clarification_source"] == "skill_required_entities"
    assert first_assistant_metadata["missing_required_entities"] == ["endorseType"]
    assert first_assistant_metadata["entities"] == first_state["entities"]
    assert first_assistant_metadata["selected_skill_id"] == "troubleshooting_agent.endo_completion_aftercare"

    second_state = await app.state.container.orchestrator.run(adapter.adapt(_chat_request("001028", session_id="s-clarify")))

    assert second_state["intent"] == "troubleshooting"
    assert second_state["sub_intent"] == "endo_completion_aftercare"
    assert second_state["need_clarification"] is False
    assert second_state["missing_required_entities"] == []
    assert second_state["entities"] == {
        "apply_seq": "930010412672222",
        "endorseType": "001028",
        "policy_no": "9200100000458846",
    }
    assert "用户补充：endorseType=001028" in second_state["rewritten_query"]
    assert second_state["subagent_result"]["selected_skill_id"] == "troubleshooting_agent.endo_completion_aftercare"

    all_messages = await app.state.container.storage.message_store.list_by_session(second_state["session_key"])
    second_assistant_metadata = all_messages[-1]["metadata"]
    assert second_assistant_metadata["need_clarification"] is False
    assert second_assistant_metadata["missing_required_entities"] == []
    assert second_assistant_metadata["entities"] == second_state["entities"]


async def test_new_strong_anchor_does_not_reuse_history_in_skill_entity_check(app_factory):
    """当前轮新强锚点不能被下游 skill 必填检查重新继承历史保单号。"""
    app = app_factory("new-anchor-no-history.sqlite3")
    adapter = RequestAdapter()
    session_key = "pingan_health:web:u001:s-new-anchor"
    await app.state.container.storage.message_store.append(
        session_key=session_key,
        role="user",
        content="保单号 9200100000458846",
        metadata={"original_query": "保单号 9200100000458846"},
    )
    await app.state.container.storage.message_store.append(
        session_key=session_key,
        role="assistant",
        content="已记录第一个保单。",
        metadata={"need_clarification": False, "entities": {"policy_no": "9200100000458846"}},
    )
    await app.state.container.storage.message_store.append(
        session_key=session_key,
        role="user",
        content="保单号 9200100000458847",
        metadata={"original_query": "保单号 9200100000458847"},
    )
    await app.state.container.storage.message_store.append(
        session_key=session_key,
        role="assistant",
        content="已记录第二个保单。",
        metadata={"need_clarification": False, "entities": {"policy_no": "9200100000458847"}},
    )

    state = await app.state.container.orchestrator.run(
        adapter.adapt(
            _chat_request(
                "保全任务完成，受理号930010412672222没有更新？",
                session_id="s-new-anchor",
            )
        )
    )

    assert state["intent"] == "troubleshooting"
    assert state["sub_intent"] == "endo_completion_aftercare"
    assert state["entities"] == {"apply_seq": "930010412672222"}
    assert state["need_clarification"] is True
    assert state["missing_required_entities"] == ["policy_no", "endorseType"]
    assert "多个" not in state["clarification_question"]
