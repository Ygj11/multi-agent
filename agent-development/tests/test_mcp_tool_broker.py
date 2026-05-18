"""MCP tool wrapper 经过 ToolBroker / PolicyGate 的测试。"""

from app.config.settings import Settings
from app.mcp.fake_connector import FakeMCPConnector
from app.schemas.tool import ToolCall
from app.tools.broker import ToolBroker
from app.tools.mcp_tools import build_mcp_tool
from app.tools.policy_gate import PolicyGate
from app.tools.registry import ToolRegistry


async def test_mcp_tool_goes_through_tool_broker_and_policy_gate():
    """已授权的 MCP wrapper 应通过 ToolBroker 正常执行。"""
    registry = ToolRegistry()
    registry.register(
        "partner_trace.get_request_detail",
        build_mcp_tool(FakeMCPConnector(), "partner_trace.get_request_detail"),
    )
    broker = ToolBroker(registry=registry, policy_gate=PolicyGate(Settings()))

    result = await broker.call(
        ToolCall(name="partner_trace.get_request_detail", arguments={"request_id": "REQ_001"})
    )

    assert result.allowed is True
    assert result.success is True
    assert result.result["found"] is True
    assert result.result["timestamp_included_in_sign"] is False


async def test_unknown_mcp_tool_is_rejected():
    """未注册的 MCP 工具应被拒绝。"""
    broker = ToolBroker(registry=ToolRegistry(), policy_gate=PolicyGate(Settings()))
    result = await broker.call(ToolCall(name="partner_trace.unknown", arguments={"request_id": "REQ_001"}))

    assert result.allowed is False
    assert result.success is False
