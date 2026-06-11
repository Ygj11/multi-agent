from __future__ import annotations

import json

import httpx

from app.integrations.base_http_client import BaseIntegrationHTTPClient
from app.integrations.knowledge_api_client import KnowledgeAPIClient
from app.runtime.context_builder import ContextBuilder
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentTask
from tests.fakes.fake_knowledge_service import FakeKnowledgeService


async def test_knowledge_api_client_sends_namespaces():
    seen_payload = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_payload.update(json.loads(request.content))
        return httpx.Response(200, json={"chunks": [{"content": "hit", "source": "doc", "score": 1.0}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    api = KnowledgeAPIClient(BaseIntegrationHTTPClient(base_url="https://knowledge.example.test", client=client))

    await api.search("query", top_k=1, namespaces=["policy"])

    assert seen_payload["namespaces"] == ["policy"]
    await client.aclose()


class NamespaceRecordingKnowledgeService(FakeKnowledgeService):
    def __init__(self):
        super().__init__()
        self.last_namespaces = None

    async def search(self, query: str, top_k: int = 3, namespaces: list[str] | None = None):
        self.last_namespaces = namespaces
        return await super().search(query, top_k, namespaces=namespaces)


async def test_context_builder_passes_agent_card_rag_namespaces_to_subagent_search():
    service = NamespaceRecordingKnowledgeService()
    builder = ContextBuilder(skills_root="app/skills", knowledge_service=service)
    task = SubAgentTask(
        name="troubleshooting_agent",
        query="query",
        intent="troubleshooting",
        session_key="s1",
        original_query="query",
        metadata={
            "agent_card": {
                "agent_name": "troubleshooting_agent",
                "display_name": "Troubleshooting",
                "description": "Troubleshooting",
                "capabilities": ["troubleshooting"],
                "supported_intents": ["troubleshooting"],
                "output_schema": "text",
                "skills": ["troubleshooting_agent.refund_failure"],
                "rag_namespaces": ["troubleshooting"],
                "version": "1",
            }
        },
    )
    parent = OrchestratorContext(
        original_query="query",
        rewritten_query="query",
        intent="troubleshooting",
        session_key="s1",
    )

    await builder.build_for_subagent(task=task, parent_context=parent, allowed_tools=[])

    assert service.last_namespaces == ["troubleshooting"]
