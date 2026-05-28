from __future__ import annotations

"""Normalize external knowledge API chunks into internal KnowledgeChunk objects."""

import heapq
import math
import re
from collections.abc import Iterable
from typing import Any

from app.knowledge.schemas import KnowledgeChunk


class KnowledgeChunkPostProcessor:
    """Map heterogeneous external chunk payloads to the internal chunk schema."""

    content_fields = ("content", "text", "chunk_text", "page_content", "passage")
    source_fields = ("source", "doc_id", "docId", "document_id", "documentId", "document_name", "title")
    score_fields = ("score", "similarity", "rerank_score", "distance_score")
    metadata_fields = ("doc_id", "docId", "document_id", "documentId", "document_name", "title", "section", "namespace")
    sensitive_keys = {
        "api_key",
        "apikey",
        "authorization",
        "bank_card",
        "card_number",
        "credential",
        "id_card",
        "password",
        "phone",
        "secret",
        "token",
    }
    _control_chars = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
    _sensitive_text_patterns = (
        (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "***ID_CARD***"),
        (re.compile(r"(?<!\d)\d{16,19}(?!\d)"), "***BANK_CARD***"),
        (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "***PHONE***"),
        (re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "***EMAIL***"),
        (
            re.compile(r"(?i)\b(secret|token|password|api[_-]?key|authorization)\s*[:=]\s*[^,;}\]\s]+(?:\s+[^,;}\]\s]+)?"),
            lambda match: f"{match.group(1)}=***",
        ),
    )

    def __init__(
        self,
        *,
        max_content_chars: int = 3000,
        max_source_chars: int = 256,
        allowed_sources: Iterable[str] | None = None,
        blocked_sources: Iterable[str] | None = None,
    ) -> None:
        self.max_content_chars = max_content_chars
        self.max_source_chars = max_source_chars
        self.allowed_sources = self._source_filter_set(allowed_sources)
        self.blocked_sources = self._source_filter_set(blocked_sources) or set()

    def normalize_many(self, raw_chunks: list[Any], top_k: int = 3) -> list[KnowledgeChunk]:
        limit = max(top_k, 0)
        if limit == 0:
            return []

        chunks: list[KnowledgeChunk] = []
        seen: set[str] = set()
        for raw in raw_chunks:
            chunk = self.normalize_one(raw)
            if chunk is None:
                continue
            dedupe_key = self._dedupe_key(chunk)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            chunks.append(chunk)
        if len(chunks) <= limit:
            chunks.sort(key=lambda item: item.score, reverse=True)
            return chunks
        return heapq.nlargest(limit, chunks, key=lambda item: item.score)

    def normalize_one(self, raw: Any) -> KnowledgeChunk | None:
        if not isinstance(raw, dict):
            raw = {"content": str(raw)}

        content = self._first_text(raw, self.content_fields)
        if not content:
            return None
        content = self._truncate(content)
        source = self._normalize_source(self._first_text(raw, self.source_fields))
        if not self._source_allowed(source):
            return None
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
        return self._mask_sensitive(metadata)

    def _truncate(self, content: str) -> str:
        normalized = self._redact_text(" ".join(self._control_chars.sub(" ", content).split()))
        if len(normalized) <= self.max_content_chars:
            return normalized
        return normalized[: self.max_content_chars].rstrip()

    def _normalize_source(self, source: str | None) -> str:
        normalized = " ".join(self._control_chars.sub(" ", source or "").split())
        normalized = self._redact_text(normalized) or "external_knowledge"
        if len(normalized) <= self.max_source_chars:
            return normalized
        return normalized[: self.max_source_chars].rstrip()

    def _source_allowed(self, source: str) -> bool:
        key = self._source_key(source)
        if self.allowed_sources is not None and key not in self.allowed_sources:
            return False
        return key not in self.blocked_sources

    @classmethod
    def _source_filter_set(cls, sources: Iterable[str] | None) -> set[str] | None:
        if sources is None:
            return None
        if isinstance(sources, str):
            sources = (sources,)
        normalized = set()
        for source in sources:
            key = cls._source_key(source)
            if key:
                normalized.add(key)
        return normalized

    @classmethod
    def _source_key(cls, source: str) -> str:
        return " ".join(cls._control_chars.sub(" ", str(source)).split()).casefold()

    @staticmethod
    def _dedupe_key(chunk: KnowledgeChunk) -> str:
        return " ".join(chunk.content.split()).casefold()

    @classmethod
    def _redact_text(cls, text: str) -> str:
        redacted = text
        for pattern, replacement in cls._sensitive_text_patterns:
            redacted = pattern.sub(replacement, redacted)
        return redacted

    @classmethod
    def _mask_sensitive(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "***" if cls._is_sensitive_key(key) else cls._mask_sensitive(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._mask_sensitive(item) for item in value]
        if isinstance(value, str):
            return cls._redact_text(value)
        return value

    @classmethod
    def _is_sensitive_key(cls, key: Any) -> bool:
        normalized = str(key).lower().replace("-", "_")
        return normalized in cls.sensitive_keys

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
                score = float(value)
                return score if math.isfinite(score) else 0.0
            except (TypeError, ValueError):
                continue
        return 0.0


KnowledgeChunkNormalizer = KnowledgeChunkPostProcessor
