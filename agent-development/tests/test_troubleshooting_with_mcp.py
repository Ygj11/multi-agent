def test_chat_req_001_blocks_without_skill_instead_of_claiming_mcp_evidence(client):
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
    assert "没有匹配到可执行的业务技能" in answer
    assert "MCP workflow" not in answer
    assert "签名校验失败" not in answer
