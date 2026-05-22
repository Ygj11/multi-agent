import pytest

from app.config.settings import Settings
from app.llm.internal_provider import InternalLLMProvider


def _provider() -> InternalLLMProvider:
    return InternalLLMProvider(Settings(internal_llm_api_url="http://llm.local/chat", internal_llm_model="default-model"))


def test_build_payload_includes_tools_when_provided():
    provider = _provider()
    tools = [{"type": "function", "function": {"name": "query_task_status", "parameters": {"type": "object"}}}]

    payload = provider._build_payload(
        messages=[{"role": "user", "content": "hi"}],
        tools=tools,
        model="m1",
        temperature=None,
        max_tokens=None,
    )

    assert payload["tools"] == tools
    assert payload["model"] == "m1"


def test_build_payload_omits_tools_when_none():
    provider = _provider()

    payload = provider._build_payload(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="m1",
        temperature=None,
        max_tokens=None,
    )

    assert "tools" not in payload


def test_parse_content_response():
    response = InternalLLMProvider._parse_response(
        {"choices": [{"message": {"content": "done"}, "finish_reason": "stop"}]},
        model="m1",
        request_id="r1",
        latency_ms=12,
    )

    assert response.content == "done"
    assert response.has_tool_calls is False
    assert response.finish_reason == "stop"


def test_parse_tool_calls_response():
    tool_calls = [{"name": "query_task_status", "arguments": {"policy_no": "9201344266"}}]

    response = InternalLLMProvider._parse_response(
        {"choices": [{"message": {"content": None, "tool_calls": tool_calls, "reasoning_content": "need tool"}, "finish_reason": "tool_calls"}]},
        model="m1",
        request_id="r1",
        latency_ms=12,
    )

    assert response.tool_calls == tool_calls
    assert response.has_tool_calls is True
    assert response.reasoning_content == "need tool"
    assert response.finish_reason == "tool_calls"


def test_parse_incomplete_response_returns_error():
    response = InternalLLMProvider._parse_response({}, model="m1", request_id="r1", latency_ms=12)

    assert response.finish_reason == "error"
    assert "incomplete_llm_response" in response.error


@pytest.mark.asyncio
async def test_http_error_returns_error(monkeypatch):
    class FakeResponse:
        status_code = 500
        text = "boom"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("app.llm.internal_provider.httpx.AsyncClient", FakeClient)
    response = await _provider().chat([{"role": "user", "content": "hi"}], request_id="r1")

    assert response.finish_reason == "error"
    assert "internal_llm_http_500" in response.error

