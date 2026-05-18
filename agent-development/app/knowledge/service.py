from __future__ import annotations

"""KnowledgeService 抽象接口。"""

from typing import Protocol

from app.knowledge.schemas import KnowledgeChunk


class KnowledgeService(Protocol):
    """独立知识服务接口，可被工具、ContextBuilder 和子 Agent 复用。"""

    async def search(self, query: str, top_k: int = 3) -> list[KnowledgeChunk]:
        """按 query 检索知识片段。"""
        ...

    async def pre_search(self, query: str, intent: str, top_k: int = 3) -> list[KnowledgeChunk]:
        """为主干流程做轻量知识预检索。"""
        ...

