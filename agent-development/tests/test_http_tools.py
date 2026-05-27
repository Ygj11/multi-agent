import httpx

from app.tools.http_tools import HTTPRequestTool, MCPHTTPCallTool


async def test_http_request_tool_is_rejected_by_default():
    tool = HTTPRequestTool(enabled=False)

    result = await tool(method="GET", url="https://api.example.test/status")

    assert result["success"] is False
    assert "disabled" in result["error"]


async def test_http_request_tool_calls_allowlisted_url_with_params():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.example.test"
        assert request.url.params["requestId"] == "REQ_001"
        return httpx.Response(200, json={"found": True, "requestId": "REQ_001"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tool = HTTPRequestTool(client=client, enabled=True, allowed_hosts=("api.example.test",))

    result = await tool(
        method="GET",
        url="https://api.example.test/logs",
        params={"requestId": "REQ_001"},
    )

    assert result["success"] is True
    assert result["body_json"]["found"] is True
    await client.aclose()


async def test_mcp_http_call_tool_posts_tool_name_and_arguments():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/mcp/tools/call"
        assert b"mcp.workflow.query_refund_task" in request.content
        assert b"REQ_001" in request.content
        return httpx.Response(200, json={"found": True, "summary": "ok"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tool = MCPHTTPCallTool(client=client, enabled=True, allowed_hosts=("mcp.example.test",))

    result = await tool(
        base_url="https://mcp.example.test",
        tool_name="mcp.workflow.query_refund_task",
        arguments={"request_id": "REQ_001"},
    )

    assert result["success"] is True
    assert result["body_json"]["summary"] == "ok"
    await client.aclose()


async def test_http_tool_rejects_non_allowlisted_host():
    tool = HTTPRequestTool(enabled=True, allowed_hosts=("api.example.test",))

    result = await tool(method="GET", url="https://evil.example.test/data")

    assert result["success"] is False
    assert "not allowlisted" in result["error"]
