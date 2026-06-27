from __future__ import annotations

"""SQLite evidence store.

Evidence is a reusable reference index for answers, verification, and future
audit review. It complements, but does not replace, the append-only
`tool_execution_logs` facts or the business-state `approval_requests` table.
"""

import json

from app.config.settings import get_settings
from app.evidence.schemas import Evidence
from app.storage.sqlite import SQLiteDatabase
from app.utils.json_utils import to_json


class EvidenceStore:
    """Persist evidence extracted from tool results and other trusted sources."""

    def __init__(self, db: SQLiteDatabase | None = None) -> None:
        self.db = db or SQLiteDatabase(get_settings().sqlite_db_path)

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
                    to_json(evidence.content),
                    evidence.summary,
                    to_json(evidence.citations),
                    to_json(evidence.redactions),
                    to_json(evidence.metadata),
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
