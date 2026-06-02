from __future__ import annotations

"""Build evidence objects from runtime events."""

from typing import Any

from app.evidence.schemas import Evidence
from app.knowledge.schemas import KnowledgeChunk


class EvidenceBuilder:
    @staticmethod
    def from_tool_result(
        *,
        session_key: str,
        tool_name: str,
        result: Any,
        request_id: str | None = None,
        trace_id: str | None = None,
        summary: str | None = None,
        redactions: list[dict[str, Any]] | None = None,
    ) -> Evidence:
        return Evidence(
            request_id=request_id,
            trace_id=trace_id,
            session_key=session_key,
            source_type="tool",
            source_name=tool_name,
            content=result,
            summary=summary or str(result)[:240],
            redactions=redactions or [],
        )

    @staticmethod
    def from_knowledge_chunk(
        *,
        session_key: str,
        chunk: KnowledgeChunk,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> Evidence:
        citation = {
            "source": chunk.source,
            "score": chunk.score,
            "metadata": chunk.metadata,
        }
        return Evidence(
            request_id=request_id,
            trace_id=trace_id,
            session_key=session_key,
            source_type="knowledge",
            source_name=chunk.source,
            content=chunk.content,
            summary=chunk.content[:240],
            citations=[citation],
            metadata=chunk.metadata,
        )

