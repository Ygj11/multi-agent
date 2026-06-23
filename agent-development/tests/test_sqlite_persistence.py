"""SQLite 持久化验收测试。"""

import json

from fastapi.testclient import TestClient

from app.storage.sqlite import SQLiteDatabase


def test_sqlite_database_initializes_all_runtime_tables(tmp_path):
    """SQLiteDatabase 是项目全部运行时表结构的唯一初始化入口。"""
    db = SQLiteDatabase(tmp_path / "schema.sqlite3")

    with db.connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        evidence_indexes = {
            row["name"]
            for row in conn.execute("PRAGMA index_list(evidence)").fetchall()
        }

    assert {
        "messages",
        "short_term_memory",
        "graph_checkpoints",
        "tool_execution_logs",
        "evidence",
        "approval_requests",
        "approval_events",
    }.issubset(tables)
    assert {"idx_evidence_request", "idx_evidence_session"}.issubset(evidence_indexes)


def test_messages_and_summary_survive_app_recreate(app_factory):
    """重建 app 后，同一 session 仍能通过 SQLite 恢复上一轮上下文。"""
    first_client = TestClient(app_factory("persist.sqlite3"))
    first = first_client.post(
        "/api/chat",
        json={
            "tenant_id": "pingan_health",
            "channel": "web",
            "user_id": "u001",
            "session_id": "s001",
            "messages": [{"role": "user", "content": "REQ_001 为什么返回 E102？"}],
        },
    )
    assert first.status_code == 200

    second_client = TestClient(app_factory("persist.sqlite3"))
    second = second_client.post(
        "/api/chat",
        json={
            "tenant_id": "pingan_health",
            "channel": "web",
            "user_id": "u001",
            "session_id": "s001",
            "messages": [{"role": "user", "content": "那这个一般是谁的问题？"}],
        },
    )

    data = second.json()
    assert second.status_code == 200
    assert data["intent"] == "troubleshooting"
    assert "上一轮" in data["rewritten_query"]
    assert "REQ_001" in data["rewritten_query"]
    assert "E102" in data["rewritten_query"]
    assert "没有匹配到可执行的业务技能" in data["answer"]


async def test_checkpoint_store_persists_by_thread_id(app_factory):
    """项目内 checkpoint_store 应按每次请求的 LangGraph thread_id 保存最终 state。"""
    app = app_factory("checkpoint.sqlite3")
    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={
            "tenant_id": "pingan_health",
            "channel": "web",
            "user_id": "u001",
            "session_id": "s001",
            "messages": [{"role": "user", "content": "REQ_001 为什么返回 E102？"}],
        },
    )
    assert response.status_code == 200
    data = response.json()
    thread_id = f"{data['session_key']}:{data['request_id']}"

    state = await app.state.container.storage.checkpoint_store.load(thread_id)

    assert state is not None
    assert state["schema_version"] == 1
    assert state["intent"] == "troubleshooting"
    assert state["session_key"] == "pingan_health:web:u001:s001"
    assert state["thread_id"] == thread_id
    assert "finalize_response" in state["graph_path"]
    assert "conversation_window" not in state
    assert "recent_messages" not in state
    assert "entity_bag" not in state
    assert "subagent_result" not in state


def test_sqlite_persistence_keeps_users_isolated(app_factory):
    """SQLite 中的消息、summary 和 checkpoint 不能跨 user_id 污染。"""
    first_client = TestClient(app_factory("isolation.sqlite3"))
    first = first_client.post(
        "/api/chat",
        json={
            "tenant_id": "pingan_health",
            "channel": "web",
            "user_id": "u001",
            "session_id": "s001",
            "messages": [{"role": "user", "content": "REQ_001 为什么返回 E102？"}],
        },
    )
    assert first.status_code == 200

    second_client = TestClient(app_factory("isolation.sqlite3"))
    second = second_client.post(
        "/api/chat",
        json={
            "tenant_id": "pingan_health",
            "channel": "web",
            "user_id": "u002",
            "session_id": "s001",
            "messages": [{"role": "user", "content": "那这个一般是谁的问题？"}],
        },
    )

    data = second.json()
    assert second.status_code == 200
    assert data["session_key"] == "pingan_health:web:u002:s001"
    assert data["intent"] == "unknown"
    assert "继续排查上一轮" not in data["rewritten_query"]


def test_sqlite_checkpoint_schema_uses_snapshot_json(app_factory):
    app = app_factory("checkpoint-schema.sqlite3")

    with app.state.container.storage.db.connect() as conn:
        checkpoint_columns = [row["name"] for row in conn.execute("PRAGMA table_info(graph_checkpoints)").fetchall()]
        approval_columns = [row["name"] for row in conn.execute("PRAGMA table_info(approval_requests)").fetchall()]

    assert checkpoint_columns == ["thread_id", "schema_version", "snapshot_json", "created_at", "updated_at"]
    assert "state_json" not in checkpoint_columns
    assert "pending_state_json" not in approval_columns
    assert "resume_state_json" in approval_columns


def test_checkpoint_table_persists_compact_snapshot_payload(app_factory):
    app = app_factory("checkpoint-payload.sqlite3")
    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={
            "tenant_id": "pingan_health",
            "channel": "web",
            "user_id": "u001",
            "session_id": "s001",
            "messages": [{"role": "user", "content": "REQ_001 为什么返回 E102？"}],
        },
    )
    assert response.status_code == 200
    data = response.json()
    thread_id = f"{data['session_key']}:{data['request_id']}"

    with app.state.container.storage.db.connect() as conn:
        row = conn.execute("SELECT schema_version, snapshot_json FROM graph_checkpoints WHERE thread_id = ?", (thread_id,)).fetchone()

    assert row["schema_version"] == 1
    snapshot = json.loads(row["snapshot_json"])
    assert snapshot["request_id"] == data["request_id"]
    for key in ("conversation_window", "recent_messages", "entity_bag", "subagent_result", "available_agents"):
        assert key not in snapshot
