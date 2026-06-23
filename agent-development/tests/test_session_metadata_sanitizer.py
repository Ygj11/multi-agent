from app.memory.short_term_memory_manager import ShortTermMemoryManager
from app.session.message_metadata_sanitizer import sanitize_message_for_runtime
from app.session.message_store import MessageStore
from app.session.session_manager import SessionManager
from app.storage.sqlite import SQLiteDatabase


def test_sanitize_message_for_runtime_keeps_business_metadata_only():
    message = {
        "role": "assistant",
        "content": "请补充保全项。",
        "metadata": {
            "original_query": "保全任务完成但保单没更新",
            "rewritten_query": "保全任务完成后保单更新错误",
            "entities": {"policy_no": "9200100000458846"},
            "need_clarification": True,
            "clarification_source": "skill_required_entities",
            "missing_required_entities": ["endorseType"],
            "missing_tool_arguments": [{"tool_name": "query_endo_task_record", "arguments": ["apply_seq"]}],
            "selected_agent": "troubleshooting_agent",
            "selected_skill_id": "troubleshooting_agent.endo_completion_aftercare",
            "decision_traces": {"intent_recognition": {"policy_version": "1.0.0"}},
            "selected_skill_metadata": {"large": "body"},
            "tool_calling_runner": {"pending_messages": [{"role": "assistant", "content": "debug"}]},
            "pending_tools": [{"type": "function"}],
        },
        "created_at": "2026-06-12T00:00:00Z",
    }

    sanitized = sanitize_message_for_runtime(message)

    assert sanitized["role"] == "assistant"
    assert sanitized["content"] == "请补充保全项。"
    assert sanitized["created_at"] == "2026-06-12T00:00:00Z"
    assert sanitized["metadata"] == {
        "original_query": "保全任务完成但保单没更新",
        "rewritten_query": "保全任务完成后保单更新错误",
        "entities": {"policy_no": "9200100000458846"},
        "need_clarification": True,
        "clarification_source": "skill_required_entities",
        "missing_required_entities": ["endorseType"],
        "missing_tool_arguments": [{"tool_name": "query_endo_task_record", "arguments": ["apply_seq"]}],
        "selected_agent": "troubleshooting_agent",
        "selected_skill_id": "troubleshooting_agent.endo_completion_aftercare",
    }
    assert "decision_traces" in message["metadata"]


async def test_session_manager_sanitizes_recent_messages_without_changing_persistence(tmp_path):
    db = SQLiteDatabase(tmp_path / "session-metadata.sqlite3")
    store = MessageStore(db)
    memory = ShortTermMemoryManager(db)
    manager = SessionManager(store, memory)
    session_key = "pingan_health:web:u001:s001"

    await store.append(
        session_key=session_key,
        role="assistant",
        content="执行保全任务完成后异常处理还缺少保全项 endorseType，请补充后我再继续处理。",
        metadata={
            "original_query": "保单号 9200100000458846 保全任务完成但没更新",
            "rewritten_query": "保单号 9200100000458846 保全任务完成但没更新",
            "entities": {"policy_no": "9200100000458846"},
            "need_clarification": True,
            "clarification_source": "skill_required_entities",
            "missing_required_entities": ["endorseType"],
            "missing_tool_arguments": [{"tool_name": "query_endo_task_record", "arguments": ["apply_seq"]}],
            "selected_skill_id": "troubleshooting_agent.endo_completion_aftercare",
            "decision_traces": {"query_rewrite": {"policy_version": "1.0.0"}},
            "selected_skill_metadata": {"name": "aftercare", "content": "large"},
            "tool_calling_runner": {"pending_messages": [{"role": "assistant", "content": "debug"}]},
        },
    )

    persisted = await store.list_by_session(session_key)
    assert persisted[-1]["metadata"]["decision_traces"]["query_rewrite"]["policy_version"] == "1.0.0"
    assert persisted[-1]["metadata"]["selected_skill_metadata"]["name"] == "aftercare"

    loaded = await manager.load_session(session_key)
    runtime_metadata = loaded["recent_messages"][-1]["metadata"]

    assert runtime_metadata["need_clarification"] is True
    assert runtime_metadata["missing_required_entities"] == ["endorseType"]
    assert runtime_metadata["missing_tool_arguments"] == [
        {"tool_name": "query_endo_task_record", "arguments": ["apply_seq"]}
    ]
    assert runtime_metadata["entities"] == {"policy_no": "9200100000458846"}
    assert runtime_metadata["selected_skill_id"] == "troubleshooting_agent.endo_completion_aftercare"
    assert "decision_traces" not in runtime_metadata
    assert "selected_skill_metadata" not in runtime_metadata
    assert "tool_calling_runner" not in runtime_metadata
