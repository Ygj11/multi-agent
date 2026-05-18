from __future__ import annotations

"""内存版 KnowledgeService。

第三阶段不接 Milvus、Elasticsearch，也不做 embedding，只用关键词检索验证 RAG 边界。
"""

from app.knowledge.schemas import KnowledgeChunk
from app.observability.logger import log_event, preview_text


class InMemoryKnowledgeService:
    """使用内置 mock knowledge chunks 的关键词检索服务。"""

    def __init__(self, chunks: list[KnowledgeChunk] | None = None) -> None:
        """初始化内置知识片段。"""
        self.chunks = chunks or self._default_chunks()

    async def search(self, query: str, top_k: int = 3) -> list[KnowledgeChunk]:
        """按关键词命中数量计算简单 score，并返回 top_k。"""
        log_event(
            "knowledge_search_started",
            node="knowledge_service",
            message="Knowledge search started",
            data={"query_preview": preview_text(query), "top_k": top_k},
        )
        scored: list[KnowledgeChunk] = []
        for chunk in self.chunks:
            score = self._score(query, chunk)
            if score > 0:
                scored.append(
                    KnowledgeChunk(
                        content=chunk.content,
                        source=chunk.source,
                        score=score,
                        metadata=chunk.metadata,
                    )
                )
        scored.sort(key=lambda item: item.score, reverse=True)
        results = scored[:top_k]
        log_event(
            "knowledge_search_finished",
            node="knowledge_service",
            message="Knowledge search finished",
            data={"query_preview": preview_text(query), "top_k": top_k, "hit_count": len(results), "sources": [chunk.source for chunk in results]},
        )
        return results

    async def pre_search(self, query: str, intent: str, top_k: int = 3) -> list[KnowledgeChunk]:
        """主干轻量预检索，当前复用关键词检索。"""
        log_event(
            "knowledge_presearch_started",
            node="knowledge_service",
            message="Knowledge presearch started",
            data={"query_preview": preview_text(query), "intent": intent, "top_k": top_k},
        )
        results = await self.search(query=f"{query} {intent}", top_k=top_k)
        log_event(
            "knowledge_presearch_finished",
            node="knowledge_service",
            message="Knowledge presearch finished",
            data={"hit_count": len(results), "sources": [chunk.source for chunk in results]},
        )
        return results

    @staticmethod
    def _score(query: str, chunk: KnowledgeChunk) -> float:
        """基于关键词命中计算确定性分数。"""
        normalized_query = query.lower()
        keywords = [str(keyword).lower() for keyword in chunk.metadata.get("keywords", [])]
        hits = sum(1 for keyword in keywords if keyword and keyword in normalized_query)
        if hits == 0:
            return 0.0
        return round(0.5 + hits * 0.15, 4)

    @staticmethod
    def _default_chunks() -> list[KnowledgeChunk]:
        """返回健康险个险接口联调场景的内置 mock knowledge。"""
        return [
            KnowledgeChunk(
                content=(
                    "E102 通常表示签名校验失败，常见原因包括签名字段排序不一致、timestamp 未参与签名、"
                    "密钥版本不一致、空值字段处理方式不一致、body 序列化方式不一致、渠道方仍使用旧版签名规则。"
                ),
                source="mock_knowledge:e102_signature",
                score=1.0,
                metadata={"keywords": ["E102", "签名", "签名校验失败", "timestamp", "密钥版本", "字段排序", "空值"]},
            ),
            KnowledgeChunk(
                content=(
                    "submitProposal 是健康险个险投保提交接口，常见联调问题包括签名失败、字段映射错误、"
                    "产品编码不一致和时间戳过期。"
                ),
                source="mock_knowledge:submit_proposal",
                score=1.0,
                metadata={"keywords": ["submitProposal", "投保提交", "联调", "接口", "时间戳"]},
            ),
            KnowledgeChunk(
                content="当前 v2 签名规则要求 timestamp 参与签名 base string，且字段排序必须与接口文档一致。",
                source="mock_knowledge:signature_v2_timestamp",
                score=1.0,
                metadata={"keywords": ["timestamp", "v2", "签名规则", "base string", "字段排序"]},
            ),
            KnowledgeChunk(
                content="密钥版本不一致会导致我方计算签名与渠道侧传入签名不一致，需要核对 secret_version。",
                source="mock_knowledge:secret_version",
                score=1.0,
                metadata={"keywords": ["密钥版本", "secret", "secret_version", "签名不一致"]},
            ),
            KnowledgeChunk(
                content="字段排序不一致是签名失败常见原因，双方必须使用同一字段集合、排序规则和大小写处理方式。",
                source="mock_knowledge:field_order",
                score=1.0,
                metadata={"keywords": ["字段排序", "排序", "字段集合", "大小写"]},
            ),
            KnowledgeChunk(
                content="空值字段处理不一致会导致签名 base string 不一致，应确认空字符串、null、缺省字段是否参与签名。",
                source="mock_knowledge:empty_field",
                score=1.0,
                metadata={"keywords": ["空值", "空字符串", "null", "缺省字段", "base string"]},
            ),
        ]
