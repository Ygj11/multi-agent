import asyncio
import inspect

import pytest

from app.integrations.base_http_client import BaseIntegrationHTTPClient
from app.integrations.knowledge_api_client import KnowledgeAPIClient
from app.integrations.log_api_client import LogAPIClient
from app.integrations.llm_api_client_example import LLMAPIClientExample
from app.integrations.long_term_memory_api_client import LongTermMemoryAPIClient
from app.integrations.vector_search_api_client import VectorSearchAPIClient
from app.integrations.insurance_core_api_client import InsuranceCoreAPIClient
from app.integrations.observability_api_client import ObservabilityAPIClient


def test_base_http_client_passes_trace_headers_and_masks_sensitive_values():
    """未来真实 API 示例必须支持 request_id / trace_id 透传和脱敏。"""
    client = BaseIntegrationHTTPClient(base_url="https://example.invalid", api_token="token")
    headers = client.build_headers(request_id="req-1", trace_id="trace-1")

    assert headers["X-Request-Id"] == "req-1"
    assert headers["X-Trace-Id"] == "trace-1"
    assert client.mask_sensitive({"password": "secret", "nested": {"token": "abc"}}) == {
        "password": "***",
        "nested": {"token": "***"},
    }


@pytest.mark.asyncio
async def test_base_http_client_reuses_one_pool_and_closes_it(monkeypatch):
    created = []

    class FakeResponse:
        status_code = 200
        url = "https://example.test/items"

        def raise_for_status(self):
            return None

        def json(self):
            return {"success": True}

    class FakeAsyncClient:
        is_closed = False

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            created.append(self)

        async def request(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return FakeResponse()

        async def aclose(self):
            self.is_closed = True

    monkeypatch.setattr("app.integrations.base_http_client.httpx.AsyncClient", FakeAsyncClient)
    client = BaseIntegrationHTTPClient(base_url="https://example.test", timeout=2.0)

    assert await client.get_json("/items") == {"success": True}
    assert await client.get_json("/items") == {"success": True}

    assert len(created) == 1
    assert len(created[0].calls) == 2
    await client.close()
    assert created[0].is_closed is True


@pytest.mark.asyncio
async def test_base_http_client_keeps_request_headers_isolated_under_concurrency(monkeypatch):
    captured_headers = []

    class FakeResponse:
        status_code = 200
        url = "https://example.test/items"

        def raise_for_status(self):
            return None

        def json(self):
            return {"success": True}

    class FakeAsyncClient:
        is_closed = False

        def __init__(self, **kwargs):
            pass

        async def request(self, *args, **kwargs):
            captured_headers.append(dict(kwargs["headers"]))
            return FakeResponse()

        async def aclose(self):
            self.is_closed = True

    monkeypatch.setattr("app.integrations.base_http_client.httpx.AsyncClient", FakeAsyncClient)
    client = BaseIntegrationHTTPClient(base_url="https://example.test")

    await asyncio.gather(
        client.get_json("/items", request_id="req-a", trace_id="trace-a"),
        client.get_json("/items", request_id="req-b", trace_id="trace-b"),
    )

    assert {headers["X-Request-Id"] for headers in captured_headers} == {"req-a", "req-b"}
    assert {headers["X-Trace-Id"] for headers in captured_headers} == {"trace-a", "trace-b"}
    await client.close()


@pytest.mark.asyncio
async def test_base_http_client_does_not_close_external_injected_client():
    class FakeAsyncClient:
        is_closed = False
        close_calls = 0

        async def aclose(self):
            self.close_calls += 1
            self.is_closed = True

    external = FakeAsyncClient()
    client = BaseIntegrationHTTPClient(base_url="https://example.test", client=external)

    await client.close()

    assert external.close_calls == 0


@pytest.mark.asyncio
async def test_knowledge_api_client_returns_empty_without_base_url():
    """真实 API 示例默认不启用，缺少真实地址时不会发起外部请求。"""
    client = KnowledgeAPIClient(BaseIntegrationHTTPClient(base_url=None))

    assert await client.search(query="E102", request_id="req-1", trace_id="trace-1") == []


def test_future_api_client_methods_keep_request_and_trace_parameters():
    """所有真实 API 示例都保留 request_id / trace_id 参数，便于后续全链路透传。"""
    methods = [
        KnowledgeAPIClient.search,
        KnowledgeAPIClient.pre_search,
        LogAPIClient.query_internal_log,
        LLMAPIClientExample.chat,
        LLMAPIClientExample.chat_json,
        LongTermMemoryAPIClient.retrieve,
        LongTermMemoryAPIClient.extract_and_update,
        VectorSearchAPIClient.search_vectors,
        VectorSearchAPIClient.keyword_search,
        InsuranceCoreAPIClient.get_policy,
        InsuranceCoreAPIClient.get_product,
        InsuranceCoreAPIClient.validate_proposal,
        ObservabilityAPIClient.emit_event,
        ObservabilityAPIClient.emit_trace_span,
    ]

    for method in methods:
        signature = inspect.signature(method)
        assert "request_id" in signature.parameters
        assert "trace_id" in signature.parameters
