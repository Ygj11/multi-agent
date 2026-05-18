"""SQLite 持久化验收测试。"""

from fastapi.testclient import TestClient


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
    assert "继续排查上一轮" in data["rewritten_query"]
    assert "E102" in data["answer"]
    assert "timestamp" in data["answer"]


async def test_checkpoint_store_persists_by_session_key(app_factory):
    """项目内 checkpoint_store 应按 session_key 保存 LangGraph 最终 state。"""
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

    state = await app.state.checkpoint_store.load("pingan_health:web:u001:s001")

    assert state is not None
    assert state["intent"] == "troubleshooting"
    assert state["session_key"] == "pingan_health:web:u001:s001"
    assert "finalize_response" in state["graph_path"]


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
