"""KnowledgeService and ContextBuilder knowledge hint tests."""

from pathlib import Path

from app.knowledge.disabled_service import DisabledKnowledgeService
from app.runtime.context_builder import ContextBuilder
from tests.fakes.fake_knowledge_service import FakeKnowledgeService


async def test_disabled_knowledge_service_returns_empty_chunks():
    service = DisabledKnowledgeService()

    assert await service.search("E102", top_k=3) == []
    assert await service.pre_search("E102", intent="troubleshooting", top_k=3) == []


async def test_context_builder_uses_lightweight_knowledge_hints():
    builder = ContextBuilder(
        skills_root=Path("app") / "skills",
        knowledge_service=FakeKnowledgeService(),
    )

    context = await builder.build_for_orchestrator(
        original_query="REQ_001 为什么返回 E102?",
        rewritten_query="排查 requestId=REQ_001 的健康险个险接口 E102 错误原因",
        intent="troubleshooting",
        session_key="pingan_health:web:u001:s001",
        recent_messages=[],
        short_summary=None,
        available_subagents=["troubleshooting_agent"],
        available_tools=["get_knowledge"],
    )

    assert context.lightweight_knowledge_hints
    assert any("fake knowledge result" in hint for hint in context.lightweight_knowledge_hints)
