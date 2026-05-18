"""ToolBroker 和 PolicyGate 验收测试。"""

from app.config.settings import Settings
from app.tools.broker import ToolBroker
from app.tools.builtin_tools import get_knowledge, query_internal_log
from app.tools.policy_gate import PolicyGate
from app.tools.registry import ToolRegistry
from app.schemas.tool import ToolCall


async def test_tool_broker_calls_allowed_tool_through_policy_gate():
    """允许的工具应经过 PolicyGate 后正常执行。"""
    registry = ToolRegistry()
    registry.register("get_knowledge", get_knowledge)
    broker = ToolBroker(registry=registry, policy_gate=PolicyGate(Settings()))

    result = await broker.call(ToolCall(name="get_knowledge", arguments={"query": "E102"}))

    assert result.allowed is True
    assert result.success is True
    assert "签名校验失败" in result.result


async def test_tool_broker_rejects_unknown_tool():
    """未知工具应被 ToolBroker 标准化拒绝。"""
    broker = ToolBroker(registry=ToolRegistry(), policy_gate=PolicyGate(Settings()))
    result = await broker.call(ToolCall(name="unknown_tool", arguments={}))
    assert result.success is False
    assert result.allowed is False


async def test_query_internal_log_req_001():
    """mock 内部日志工具应返回 REQ_001 的 E102 数据。"""
    registry = ToolRegistry()
    registry.register("query_internal_log", query_internal_log)
    broker = ToolBroker(registry=registry, policy_gate=PolicyGate(Settings()))

    result = await broker.call(ToolCall(name="query_internal_log", arguments={"request_id": "REQ_001"}))

    assert result.success is True
    assert result.result["error_code"] == "E102"
