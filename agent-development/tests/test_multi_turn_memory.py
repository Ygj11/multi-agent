"""多轮对话短期记忆验收测试。"""


def test_second_turn_uses_first_turn_context(client):
    """第二轮追问应能复用第一轮 E102 上下文。"""
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
    assert "继续排查上一轮" in data["rewritten_query"]
    assert "E102" in data["answer"]
    assert "渠道" in data["answer"] or "timestamp" in data["answer"]
