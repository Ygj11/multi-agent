import httpx

from app.config.settings import Settings
from app.schemas.tool import ToolCall
from app.tools.broker import ToolBroker
from app.tools.http_tools import HTTPRequestTool, MCPHTTPCallTool
from app.tools.policy_gate import PolicyGate
from app.tools.registry import ToolRegistry


async def test_http_request_tool_is_rejected_by_default():
    """HTTP 工具默认关闭，避免子 Agent 未授权访问外部接口。"""
    registry = ToolRegistry()
    registry.register("http_request", HTTPRequestTool())
    broker = ToolBroker(registry=registry, policy_gate=PolicyGate(Settings()))

    result = await broker.call(
        ToolCall(name="http_request", arguments={"method": "GET", "url": "https://api.example.test/status"})
    )

    assert result.allowed is False
    assert result.success is False
    assert "disabled" in result.error


async def test_http_request_tool_calls_allowlisted_url_with_params():
    """HTTP 工具开启后可以带 URL 和 params 调用白名单 host。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.example.test"
        assert request.url.params["requestId"] == "REQ_001"
        return httpx.Response(200, json={"found": True, "requestId": "REQ_001"})

    registry = ToolRegistry()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    registry.register("http_request", HTTPRequestTool(client=client))
    broker = ToolBroker(
        registry=registry,
        policy_gate=PolicyGate(
            Settings(enable_http_tools=True, allowed_http_tool_hosts=("api.example.test",))
        ),
    )

    result = await broker.call(
        ToolCall(
            name="http_request",
            arguments={
                "method": "GET",
                "url": "https://api.example.test/logs",
                "params": {"requestId": "REQ_001"},
            },
        )
    )

    assert result.allowed is True
    assert result.success is True
    assert result.result["body_json"]["found"] is True
    await client.aclose()


async def test_mcp_http_call_tool_posts_tool_name_and_arguments():
    """MCP HTTP 工具可通过 base_url、tool_name 和 arguments 调用 HTTP 网关。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/mcp/tools/call"
        assert b"mcp.workflow.query_refund_task" in request.content
        assert b"REQ_001" in request.content
        return httpx.Response(200, json={"found": True, "summary": "ok"})

    registry = ToolRegistry()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    registry.register("mcp_http.call_tool", MCPHTTPCallTool(client=client))
    broker = ToolBroker(
        registry=registry,
        policy_gate=PolicyGate(
            Settings(enable_http_tools=True, allowed_http_tool_hosts=("mcp.example.test",))
        ),
    )

    result = await broker.call(
        ToolCall(
            name="mcp_http.call_tool",
            arguments={
                "base_url": "https://mcp.example.test",
                "tool_name": "mcp.workflow.query_refund_task",
                "arguments": {"request_id": "REQ_001"},
            },
        )
    )

    assert result.allowed is True
    assert result.success is True
    assert result.result["body_json"]["summary"] == "ok"
    await client.aclose()


async def test_http_tool_rejects_non_allowlisted_host():
    """HTTP 工具即使开启，也必须限制在 host 白名单内。"""
    registry = ToolRegistry()
    registry.register("http_request", HTTPRequestTool())
    broker = ToolBroker(
        registry=registry,
        policy_gate=PolicyGate(
            Settings(enable_http_tools=True, allowed_http_tool_hosts=("api.example.test",))
        ),
    )

    result = await broker.call(
        ToolCall(name="http_request", arguments={"method": "GET", "url": "https://evil.example.test/data"})
    )

    assert result.allowed is False
    assert "not allowlisted" in result.error
