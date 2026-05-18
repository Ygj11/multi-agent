from __future__ import annotations

"""SQLite tool call audit store。"""

import json
from typing import Any

from app.config.settings import get_settings
from app.storage.sqlite import SQLiteDatabase


SENSITIVE_KEYS = {"secret", "token", "password", "api_key", "authorization"}


class ToolCallLogStore:
    """负责把 ToolBroker 的每次工具调用写入 tool_call_logs。"""

    def __init__(self, db: SQLiteDatabase | None = None) -> None:
        """注入 SQLiteDatabase；未注入时使用默认 SQLITE_DB_PATH。"""
        self.db = db or SQLiteDatabase(get_settings().sqlite_db_path)

    async def append(
        self,
        *,
        request_id: str | None,
        trace_id: str | None,
        session_key: str | None,
        tool_name: str,
        arguments: dict[str, Any],
        allowed: bool,
        success: bool,
        result: Any,
        error: str | None,
        started_at: str,
        finished_at: str,
        duration_ms: int,
        created_at: str,
    ) -> None:
        """写入一条工具调用审计日志。"""
        arguments_json = self._to_json(self._mask_sensitive(arguments))
        result_json = self._to_json(result) if result is not None else None

        def write(conn):
            conn.execute(
                """
                INSERT INTO tool_call_logs(
                    request_id, trace_id, session_key, tool_name, arguments_json,
                    allowed, success, result_json, error, started_at, finished_at,
                    duration_ms, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    trace_id,
                    session_key,
                    tool_name,
                    arguments_json,
                    1 if allowed else 0,
                    1 if success else 0,
                    result_json,
                    error,
                    started_at,
                    finished_at,
                    duration_ms,
                    created_at,
                ),
            )

        await self.db.run(write)

    async def list_by_session(self, session_key: str) -> list[dict[str, Any]]:
        """按 session_key 读取工具调用日志。"""

        def read(conn):
            rows = conn.execute(
                """
                SELECT *
                FROM tool_call_logs
                WHERE session_key = ?
                ORDER BY id ASC
                """,
                (session_key,),
            ).fetchall()
            return [self._row_to_dict(row) for row in rows]

        return await self.db.run(read)

    async def list_all(self) -> list[dict[str, Any]]:
        """读取全部工具调用日志，主要供测试使用。"""

        def read(conn):
            rows = conn.execute("SELECT * FROM tool_call_logs ORDER BY id ASC").fetchall()
            return [self._row_to_dict(row) for row in rows]

        return await self.db.run(read)

    async def clear(self) -> None:
        """清空工具调用日志，主要供测试使用。"""

        def delete(conn):
            conn.execute("DELETE FROM tool_call_logs")

        await self.db.run(delete)

    @classmethod
    def _mask_sensitive(cls, value: Any) -> Any:
        """递归脱敏常见敏感字段。"""
        if isinstance(value, dict):
            masked = {}
            for key, item in value.items():
                if str(key).lower() in SENSITIVE_KEYS:
                    masked[key] = "***"
                else:
                    masked[key] = cls._mask_sensitive(item)
            return masked
        if isinstance(value, list):
            return [cls._mask_sensitive(item) for item in value]
        return value

    @staticmethod
    def _to_json(value: Any) -> str:
        """将值安全序列化为 JSON 字符串。"""
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            return json.dumps(str(value), ensure_ascii=False)

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        """将 SQLite row 转为普通 dict。"""
        return {
            "id": row["id"],
            "request_id": row["request_id"],
            "trace_id": row["trace_id"],
            "session_key": row["session_key"],
            "tool_name": row["tool_name"],
            "arguments_json": row["arguments_json"],
            "allowed": bool(row["allowed"]),
            "success": bool(row["success"]),
            "result_json": row["result_json"],
            "error": row["error"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "duration_ms": row["duration_ms"],
            "created_at": row["created_at"],
        }

