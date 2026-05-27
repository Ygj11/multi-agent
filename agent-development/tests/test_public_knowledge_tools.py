from app.knowledge.disabled_service import DisabledKnowledgeService
from app.tools.builtin_tools import build_get_knowledge_tool
from app.tools.public_tools import build_rag_search_tool
from tests.fakes.fake_knowledge_service import FakeKnowledgeService


async def test_public_knowledge_tools_do_not_crash_when_disabled():
    service = DisabledKnowledgeService()
    get_knowledge = build_get_knowledge_tool(service)
    rag_search = build_rag_search_tool(service)

    assert await get_knowledge("E102") == "knowledge api disabled"
    assert await rag_search("E102") == "knowledge api disabled"


async def test_public_knowledge_tools_return_fake_chunks():
    service = FakeKnowledgeService()
    get_knowledge = build_get_knowledge_tool(service)
    rag_search = build_rag_search_tool(service)

    assert await get_knowledge("test") == "fake knowledge result"
    assert await rag_search("test") == "fake knowledge result"
