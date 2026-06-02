from __future__ import annotations

"""SQLite evidence store."""

import json
from typing import Any

from app.config.settings import get_settings
from app.evidence.schemas import Evidence
from app.storage.sqlite import SQLiteDatabase


class EvidenceStore:
    def __init__(self, db: SQLiteDatabase | None = None) -> None:
        self.db = db or SQLiteDatabase(get_settings().sqlite_db_path)
        self._initialize()

    def _initialize(self) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    request_id TEXT,
                    trace_id TEXT,
                    session_key TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    summary TEXT,
                    citations_json TEXT NOT NULL,
                    redactions_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_request ON evidence(request_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_session ON evidence(session_key)")
            conn.commit()

    async def save(self, evidence: Evidence) -> Evidence:
        def write(conn):
            conn.execute(
                """
                INSERT OR REPLACE INTO evidence(
                    evidence_id, request_id, trace_id, session_key, source_type, source_name,
                    content_json, summary, citations_json, redactions_json, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.evidence_id,
                    evidence.request_id,
                    evidence.trace_id,
                    evidence.session_key,
                    evidence.source_type,
                    evidence.source_name,
                    self._to_json(evidence.content),
                    evidence.summary,
                    self._to_json(evidence.citations),
                    self._to_json(evidence.redactions),
                    self._to_json(evidence.metadata),
                    evidence.created_at,
                ),
            )

        await self.db.run(write)
        return evidence

    async def list_by_request(self, request_id: str) -> list[Evidence]:
        def read(conn):
            rows = conn.execute(
                "SELECT * FROM evidence WHERE request_id = ? ORDER BY created_at ASC",
                (request_id,),
            ).fetchall()
            return [self._row_to_evidence(row) for row in rows]

        return await self.db.run(read)

    async def list_by_session(self, session_key: str) -> list[Evidence]:
        def read(conn):
            rows = conn.execute(
                "SELECT * FROM evidence WHERE session_key = ? ORDER BY created_at ASC",
                (session_key,),
            ).fetchall()
            return [self._row_to_evidence(row) for row in rows]

        return await self.db.run(read)

    @classmethod
    def _row_to_evidence(cls, row) -> Evidence:
        return Evidence(
            evidence_id=row["evidence_id"],
            request_id=row["request_id"],
            trace_id=row["trace_id"],
            session_key=row["session_key"],
            source_type=row["source_type"],
            source_name=row["source_name"],
            content=json.loads(row["content_json"]),
            summary=row["summary"],
            citations=json.loads(row["citations_json"]),
            redactions=json.loads(row["redactions_json"]),
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _to_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

