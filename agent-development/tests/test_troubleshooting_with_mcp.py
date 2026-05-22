def test_chat_req_001_mentions_local_evidence_and_mcp_client_boundary(client):
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
    assert "MCP workflow" in answer or "密钥版本" in answer

