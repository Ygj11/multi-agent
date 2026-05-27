import json

import httpx

from app.integrations.base_http_client import BaseIntegrationHTTPClient
from app.integrations.knowledge_api_client import KnowledgeAPIClient


async def test_knowledge_api_client_normalizes_search_chunks():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/knowledge/search"
        payload = json.loads(request.content)
        assert payload["query"] == "E102"
        assert payload["top_k"] == 2
        return httpx.Response(
            200,
            json={
                "chunks": [
                    {"text": "first", "doc_id": "doc-a", "score": 0.4},
                    {"page_content": "second", "document_name": "doc-b", "score": 0.9},
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    api = KnowledgeAPIClient(BaseIntegrationHTTPClient(base_url="https://knowledge.example.test", client=client))

    chunks = await api.search("E102", top_k=2, request_id="req-1", trace_id="trace-1")

    assert [chunk.content for chunk in chunks] == ["second", "first"]
    assert chunks[0].source == "doc-b"
    assert chunks[0].metadata["raw"]["page_content"] == "second"
    await client.aclose()


async def test_knowledge_api_client_normalizes_pre_search_nested_chunks():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/knowledge/pre-search"
        return httpx.Response(
            200,
            json={"data": {"results": [{"passage": "hint", "title": "doc-title", "similarity": 0.7}]}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    api = KnowledgeAPIClient(BaseIntegrationHTTPClient(base_url="https://knowledge.example.test", client=client))

    chunks = await api.pre_search("query", intent="troubleshooting", top_k=1)

    assert len(chunks) == 1
    assert chunks[0].content == "hint"
    assert chunks[0].source == "doc-title"
    await client.aclose()
