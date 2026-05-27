from __future__ import annotations

"""SQLite tool execution log store."""

import json
from typing import Any

from app.config.settings import get_settings
from app.storage.sqlite import SQLiteDatabase


SENSITIVE_KEYS = {"secret", "token", "password", "api_key", "authorization"}


def mask_sensitive(value: Any) -> Any:
    """Recursively mask common sensitive fields before writing tool logs."""
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                masked[key] = "***"
            else:
                masked[key] = mask_sensitive(item)
        return masked
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    return value


def to_json(value: Any) -> str:
    """Safely serialize a value as a JSON string."""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


class ToolExecutionLogStore:
    """Writes ToolExecutor logs to tool_execution_logs."""

    def __init__(self, db: SQLiteDatabase | None = None) -> None:
        self.db = db or SQLiteDatabase(get_settings().sqlite_db_path)

    async def append(
        self,
        *,
        request_id: str | None,
        trace_id: str | None,
        session_key: str | None,
        agent_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        success: bool,
        result: Any,
        error: str | None,
        started_at: str,
        finished_at: str,
        duration_ms: int,
        source: str | None = None,
        server_name: str | None = None,
        original_tool_name: str | None = None,
        approval_id: str | None = None,
    ) -> None:
        arguments_json = to_json(mask_sensitive(arguments))
        result_json = to_json(result) if result is not None else None

        def write(conn):
            conn.execute(
                """
                INSERT INTO tool_execution_logs(
                    request_id, trace_id, session_key, agent_name, tool_name,
                    arguments_json, success, result_json, error, started_at,
                    finished_at, duration_ms, source, server_name, original_tool_name,
                    approval_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    trace_id,
                    session_key,
                    agent_name,
                    tool_name,
                    arguments_json,
                    1 if success else 0,
                    result_json,
                    error,
                    started_at,
                    finished_at,
                    duration_ms,
                    source,
                    server_name,
                    original_tool_name,
                    approval_id,
                ),
            )

        await self.db.run(write)

    async def list_by_session(self, session_key: str) -> list[dict[str, Any]]:
        def read(conn):
            rows = conn.execute(
                """
                SELECT *
                FROM tool_execution_logs
                WHERE session_key = ?
                ORDER BY id ASC
                """,
                (session_key,),
            ).fetchall()
            return [self._row_to_dict(row) for row in rows]

        return await self.db.run(read)

    async def list_all(self) -> list[dict[str, Any]]:
        def read(conn):
            rows = conn.execute("SELECT * FROM tool_execution_logs ORDER BY id ASC").fetchall()
            return [self._row_to_dict(row) for row in rows]

        return await self.db.run(read)

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "request_id": row["request_id"],
            "trace_id": row["trace_id"],
            "session_key": row["session_key"],
            "agent_name": row["agent_name"],
            "tool_name": row["tool_name"],
            "arguments_json": row["arguments_json"],
            "success": bool(row["success"]),
            "result_json": row["result_json"],
            "error": row["error"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "duration_ms": row["duration_ms"],
            "source": row["source"] if "source" in row.keys() else None,
            "server_name": row["server_name"] if "server_name" in row.keys() else None,
            "original_tool_name": row["original_tool_name"] if "original_tool_name" in row.keys() else None,
            "approval_id": row["approval_id"] if "approval_id" in row.keys() else None,
        }
