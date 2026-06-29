from __future__ import annotations

"""SQLite 工具执行日志存储。

这里是 ToolExecutor 每次尝试调用工具的权威流水账，保存脱敏参数、
工具结果/错误、耗时、来源和 approval_id。审批工作流状态仍属于
`ApprovalStore`；可复用的 Evidence 只保存摘要，并通过 tool_log_id 指回这里。
"""

import json
from typing import Any

from app.config.settings import get_settings
from app.storage.sqlite import SQLiteDatabase
from app.utils.json_utils import to_json


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


class ToolExecutionLogStore:
    """Writes append-only ToolExecutor facts to tool_execution_logs."""

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
        approval_id: str | None = None,
    ) -> int:
        arguments_json = to_json(mask_sensitive(arguments))
        result_json = to_json(result) if result is not None else None

        def write(conn):
            cursor = conn.execute(
                """
                INSERT INTO tool_execution_logs(
                    request_id, trace_id, session_key, agent_name, tool_name,
                    arguments_json, success, result_json, error, started_at,
                    finished_at, duration_ms, source, server_name, approval_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    approval_id,
                ),
            )
            return int(cursor.lastrowid)

        return await self.db.run(write)

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

    async def get_by_id(self, log_id: int) -> dict[str, Any] | None:
        def read(conn):
            row = conn.execute(
                """
                SELECT *
                FROM tool_execution_logs
                WHERE id = ?
                """,
                (log_id,),
            ).fetchone()
            return self._row_to_dict(row) if row else None

        item = await self.db.run(read)
        return self._with_parsed_result(item) if item else None

    async def find_success_by_approval(self, approval_id: str) -> dict[str, Any] | None:
        """Return the first successful execution for an approval id, if any."""

        def read(conn):
            row = conn.execute(
                """
                SELECT *
                FROM tool_execution_logs
                WHERE approval_id = ? AND success = 1
                ORDER BY id ASC
                LIMIT 1
                """,
                (approval_id,),
            ).fetchone()
            return self._row_to_dict(row) if row else None

        item = await self.db.run(read)
        return self._with_parsed_result(item) if item else None

    @staticmethod
    def _with_parsed_result(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if item and item.get("result_json"):
            try:
                item["result"] = json.loads(item["result_json"])
            except json.JSONDecodeError:
                item["result"] = item["result_json"]
        return item

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
            "approval_id": row["approval_id"] if "approval_id" in row.keys() else None,
        }
