from __future__ import annotations

"""Normalize external knowledge API chunks into internal KnowledgeChunk objects."""

from typing import Any

from app.knowledge.schemas import KnowledgeChunk


class KnowledgeChunkPostProcessor:
    """Map heterogeneous external chunk payloads to the internal chunk schema."""

    content_fields = ("content", "text", "chunk_text", "page_content", "passage")
    source_fields = ("source", "doc_id", "docId", "document_id", "documentId", "document_name", "title")
    score_fields = ("score", "similarity", "rerank_score", "distance_score")
    metadata_fields = ("doc_id", "docId", "document_id", "documentId", "document_name", "title", "section", "namespace")

    def __init__(self, *, max_content_chars: int = 3000) -> None:
        self.max_content_chars = max_content_chars

    def normalize_many(self, raw_chunks: list[Any], top_k: int = 3) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        seen: set[str] = set()
        for raw in raw_chunks:
            chunk = self.normalize_one(raw)
            if chunk is None:
                continue
            dedupe_key = chunk.content.strip()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            chunks.append(chunk)
        chunks.sort(key=lambda item: item.score, reverse=True)
        return chunks[: max(top_k, 0)]

    def normalize_one(self, raw: Any) -> KnowledgeChunk | None:
        if not isinstance(raw, dict):
            raw = {"content": str(raw)}

        content = self._first_text(raw, self.content_fields)
        if not content:
            return None
        content = self._truncate(content)
        source = self._first_text(raw, self.source_fields) or "external_knowledge"
        score = self._first_float(raw, self.score_fields)
        metadata = self._metadata(raw)

        return KnowledgeChunk(
            content=content,
            source=source,
            score=score,
            metadata=metadata,
        )

    def _metadata(self, raw: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), dict) else {}
        for field in self.metadata_fields:
            if field in raw and raw[field] not in (None, ""):
                metadata[field] = raw[field]
        metadata["raw"] = raw
        return metadata

    def _truncate(self, content: str) -> str:
        normalized = " ".join(content.split())
        if len(normalized) <= self.max_content_chars:
            return normalized
        return normalized[: self.max_content_chars].rstrip()

    @staticmethod
    def _first_text(raw: dict[str, Any], fields: tuple[str, ...]) -> str | None:
        for field in fields:
            value = raw.get(field)
            if value not in (None, ""):
                text = str(value).strip()
                if text:
                    return text
        return None

    @staticmethod
    def _first_float(raw: dict[str, Any], fields: tuple[str, ...]) -> float:
        for field in fields:
            value = raw.get(field)
            if value in (None, ""):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0


KnowledgeChunkNormalizer = KnowledgeChunkPostProcessor
