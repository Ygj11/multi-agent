"""FastAPI /api/chat 问题排查验收测试。"""


def test_chat_troubleshooting_req_001(client):
    """REQ_001 的 E102 请求应路由到排查 agent，但无匹配 skill 时不执行泛化诊断。"""
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
    assert "没有匹配到可执行的业务技能" in data["answer"]
    assert "签名校验失败" not in data["answer"]
