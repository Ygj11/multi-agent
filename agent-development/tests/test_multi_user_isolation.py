"""多用户 session_key 隔离验收测试。"""


def test_same_session_id_different_users_are_isolated(client):
    """相同 session_id 但不同 user_id 的上下文不能互相污染。"""
    response_u1 = client.post(
        "/api/chat",
        json={
            "tenant_id": "pingan_health",
            "channel": "web",
            "user_id": "u001",
            "session_id": "s001",
            "messages": [{"role": "user", "content": "REQ_001 为什么返回 E102？"}],
        },
    )
    assert response_u1.status_code == 200

    response_u2 = client.post(
        "/api/chat",
        json={
            "tenant_id": "pingan_health",
            "channel": "web",
            "user_id": "u002",
            "session_id": "s001",
            "messages": [{"role": "user", "content": "那这个一般是谁的问题？"}],
        },
    )
    assert response_u2.status_code == 200
    data_u2 = response_u2.json()

    assert response_u1.json()["session_key"] == "pingan_health:web:u001:s001"
    assert data_u2["session_key"] == "pingan_health:web:u002:s001"
    assert data_u2["intent"] == "unknown"
    assert "继续排查上一轮" not in data_u2["rewritten_query"]
