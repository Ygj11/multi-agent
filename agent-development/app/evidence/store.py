from __future__ import annotations

"""SQLite Evidence 存储。

Evidence 是答案验证、Repair 和审计复查使用的轻量证据索引。它不替代
append-only 的 `tool_execution_logs`，也不替代审批业务状态表
`approval_requests`。工具类 Evidence 只保存 summary 和 tool_log_id；
需要完整工具结果时，按 tool_log_id 回查 `tool_execution_logs`。
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
                INSERT INTO evidence(
                    evidence_id, request_id, trace_id, session_key, source_type, source_name,
                    tool_log_id, summary, citations_json, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.evidence_id,
                    evidence.request_id,
                    evidence.trace_id,
                    evidence.session_key,
                    evidence.source_type,
                    evidence.source_name,
                    evidence.tool_log_id,
                    evidence.summary,
                    to_json(evidence.citations),
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
            tool_log_id=row["tool_log_id"],
            summary=row["summary"],
            citations=json.loads(row["citations_json"]),
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
        )
