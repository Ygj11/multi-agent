"""FakeMCPConnector 测试。"""

from app.mcp.fake_connector import FakeMCPConnector


async def test_fake_mcp_list_tools():
    """FakeMCPConnector 应暴露 partner trace 工具。"""
    connector = FakeMCPConnector()
    tools = await connector.list_tools()
    assert tools[0]["name"] == "partner_trace.get_request_detail"


async def test_fake_mcp_call_tool_req_001():
    """REQ_001 渠道侧 trace 应显示旧版签名规则且未包含 timestamp。"""
    connector = FakeMCPConnector()
    result = await connector.call_tool(
        "partner_trace.get_request_detail",
        {"request_id": "REQ_001"},
    )

    assert result["found"] is True
    assert result["partner_signature_rule_version"] == "v1"
    assert result["timestamp_included_in_sign"] is False
    assert "timestamp" in result["summary"]


async def test_fake_mcp_call_tool_unknown_request_id():
    """未知 requestId 应返回 found=false。"""
    connector = FakeMCPConnector()
    result = await connector.call_tool(
        "partner_trace.get_request_detail",
        {"request_id": "REQ_UNKNOWN"},
    )

    assert result["found"] is False

