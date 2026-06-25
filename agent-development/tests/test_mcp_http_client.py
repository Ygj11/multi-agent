import pytest

from app.mcp.client import HTTPMCPClient
from app.mcp.schemas import MCPServerConfig


class _Response:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


@pytest.mark.asyncio
async def test_http_mcp_client_reuses_one_pool_and_closes_it(monkeypatch):
    created = []

    class FakeAsyncClient:
        is_closed = False

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            created.append(self)

        async def post(self, url, *, json):
            self.calls.append((url, json))
            if json["method"] == "tools/list":
                return _Response({"result": {"tools": []}})
            return _Response({"result": {}})

        async def aclose(self):
            self.is_closed = True

    monkeypatch.setattr("app.mcp.client.httpx.AsyncClient", FakeAsyncClient)
    client = HTTPMCPClient(
        MCPServerConfig(server_name="workflow", enabled=True, transport="http", url="https://mcp.example.test", timeout=3.0)
    )

    await client.initialize()
    assert await client.list_tools() == []
    assert await client.call_tool("query_task", {"apply_seq": "930021042875719"}) == {}

    assert len(created) == 1
    assert len(created[0].calls) == 3
    assert created[0].is_closed is False

    await client.close()

    assert created[0].is_closed is True
