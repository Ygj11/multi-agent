"""KnowledgeService 和 ContextBuilder 知识提示测试。"""

from pathlib import Path

from app.knowledge.in_memory_service import InMemoryKnowledgeService
from app.runtime.context_builder import ContextBuilder


async def test_knowledge_service_search_e102():
    """E102 query 应能检索到签名校验失败知识。"""
    service = InMemoryKnowledgeService()
    chunks = await service.search("REQ_001 为什么返回 E102？", top_k=3)

    assert chunks
    assert "签名校验失败" in chunks[0].content
    assert chunks[0].source
    assert chunks[0].score > 0
    assert isinstance(chunks[0].metadata, dict)


async def test_context_builder_uses_lightweight_knowledge_hints():
    """ContextBuilder 应通过 KnowledgeService 构建轻量知识提示。"""
    builder = ContextBuilder(
        skills_root=Path("app") / "skills",
        knowledge_service=InMemoryKnowledgeService(),
    )

    context = await builder.build_for_orchestrator(
        original_query="REQ_001 为什么返回 E102？",
        rewritten_query="排查 requestId=REQ_001 的健康险个险接口 E102 错误原因",
        intent="troubleshooting",
        session_key="pingan_health:web:u001:s001",
        recent_messages=[],
        short_summary=None,
        available_subagents=["troubleshooting_agent"],
        available_tools=["get_knowledge"],
    )

    assert context.lightweight_knowledge_hints
    assert any("签名校验失败" in hint for hint in context.lightweight_knowledge_hints)

