from app.knowledge.disabled_service import DisabledKnowledgeService
from app.tools.public_tools import build_rag_search_tool
from tests.fakes.fake_knowledge_service import FakeKnowledgeService


async def test_public_knowledge_tools_do_not_crash_when_disabled():
    service = DisabledKnowledgeService()
    rag_search = build_rag_search_tool(service)

    assert await rag_search("E102") == "knowledge api disabled"


async def test_public_knowledge_tools_return_fake_chunks():
    service = FakeKnowledgeService()
    rag_search = build_rag_search_tool(service)

    assert await rag_search("test") == "fake knowledge result"
