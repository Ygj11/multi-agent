"""问题排查 Agent 综合内部日志、知识和 MCP trace 的测试。"""

from fastapi.testclient import TestClient


def test_chat_req_001_mentions_partner_trace(client):
    """REQ_001 端到端回答应包含渠道侧 trace 和旧版签名规则证据。"""
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
    answer = response.json()["answer"]
    assert "E102" in answer
    assert "签名校验失败" in answer
    assert "timestamp" in answer
    assert "渠道侧 trace" in answer
    assert "旧版" in answer or "未包含 timestamp" in answer
