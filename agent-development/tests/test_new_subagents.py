def test_compliance_security_agent_routes_and_masks_sensitive_content(client):
    """合规安全 Agent 能识别敏感信息和外发风险。"""
    response = client.post(
        "/api/chat",
        json={
            "tenant_id": "tenant-a",
            "channel": "web",
            "user_id": "user-a",
            "session_id": "compliance",
            "messages": [
                {
                    "role": "user",
                    "content": "请做合规检查：手机号13800138000，身份证110101199003074233，健康告知能不能外发给渠道？",
                }
            ],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["intent"] == "compliance_review"
    assert "合规安全检查" in body["answer"]
    assert "风险等级 high" in body["answer"]
    assert "13800138000" not in body["answer"]
    assert "110101199003074233" not in body["answer"]


def test_document_parse_agent_extracts_markdown_interface_fields_and_errors(client):
    """文档解析 Agent 能从 markdown 文本中提取接口、字段和错误码。"""
    response = client.post(
        "/api/chat",
        json={
            "tenant_id": "tenant-a",
            "channel": "web",
            "user_id": "user-a",
            "session_id": "document",
            "messages": [
                {
                    "role": "user",
                    "content": "# submitProposal 接口文档\n请解析文档。字段：appId timestamp sign amount。错误码：E102 表示签名失败。",
                }
            ],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["intent"] == "document_parse"
    assert "文档解析完成" in body["answer"]
    assert "submitProposal" in body["answer"]
    assert "timestamp" in body["answer"]
    assert "E102" in body["answer"]


from fastapi.testclient import TestClient
import pytest


@pytest.mark.asyncio
async def test_change_impact_analysis_agent_uses_knowledge_tool(app_factory):
    """变更影响分析 Agent 能分析签名规则变更并通过 get_knowledge 查询知识。"""
    app = app_factory("impact.sqlite3")
    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={
            "tenant_id": "tenant-a",
            "channel": "web",
            "user_id": "user-a",
            "session_id": "impact",
            "messages": [
                {
                    "role": "user",
                    "content": "请做变更影响分析：submitProposal 签名规则变更，timestamp 必须参与签名，可能影响 E102。",
                }
            ],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["intent"] == "change_impact_analysis"
    assert "变更影响分析完成" in body["answer"]
    assert "submitProposal" in body["answer"]
    assert "timestamp" in body["answer"]
    assert "get_knowledge" in body["answer"]

    logs = await app.state.tool_call_log_store.list_by_session(body["session_key"])
    assert any(item["tool_name"] == "get_knowledge" for item in logs)
