"""FastAPI /api/chat 问题排查验收测试。"""


def test_chat_troubleshooting_req_001(client):
    """REQ_001 的 E102 请求应返回包含关键排查点的答案。"""
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
    assert data["session_key"] == "pingan_health:web:u001:s001"
    assert data["intent"] == "troubleshooting"
    assert data["rewritten_query"] == "排查 requestId=REQ_001 的健康险个险接口 E102 错误原因"
    assert "E102" in data["answer"]
    assert "签名校验失败" in data["answer"]
    assert "timestamp" in data["answer"]
    assert "密钥版本" in data["answer"] or "字段排序" in data["answer"]
    assert "渠道侧 trace" in data["answer"]
