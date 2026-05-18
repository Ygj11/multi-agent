from __future__ import annotations

"""SQLite 消息存储。"""

import json
from datetime import UTC, datetime
from typing import Any

from app.config.settings import get_settings
from app.observability.logger import log_event, preview_text
from app.storage.sqlite import SQLiteDatabase


class MessageStore:
    """按 session_key 将消息持久化到 SQLite。"""

    def __init__(self, db: SQLiteDatabase | None = None) -> None:
        """注入 SQLiteDatabase；未注入时使用默认 SQLITE_DB_PATH。"""
        self.db = db or SQLiteDatabase(get_settings().sqlite_db_path)

    async def append(
        self,
        session_key: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """向 messages 表追加一条消息，并返回标准消息 dict。"""
        message = {
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "created_at": datetime.now(UTC).isoformat(),
        }

        def write(conn):
            conn.execute(
                """
                INSERT INTO messages(session_key, role, content, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_key,
                    role,
                    content,
                    json.dumps(message["metadata"], ensure_ascii=False),
                    message["created_at"],
                ),
            )

        await self.db.run(write)
        log_event(
            "user_message_saved" if role == "user" else "assistant_message_saved" if role == "assistant" else "message_saved",
            session_key=session_key,
            node="message_store",
            message=f"{role} message saved",
            data={"role": role, "content_preview": preview_text(content)},
        )
        return message

    async def list_by_session(self, session_key: str, limit: int | None = None) -> list[dict[str, Any]]:
        """按 session_key 读取消息；limit 不为空时返回最近 N 条。"""

        def read(conn):
            if limit is None:
                rows = conn.execute(
                    """
                    SELECT role, content, metadata_json, created_at
                    FROM messages
                    WHERE session_key = ?
                    ORDER BY id ASC
                    """,
                    (session_key,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT role, content, metadata_json, created_at
                    FROM (
                        SELECT id, role, content, metadata_json, created_at
                        FROM messages
                        WHERE session_key = ?
                        ORDER BY id DESC
                        LIMIT ?
                    )
                    ORDER BY id ASC
                    """,
                    (session_key, limit),
                ).fetchall()
            return [self._row_to_message(row) for row in rows]

        return await self.db.run(read)

    async def clear(self) -> None:
        """清空 messages 表，主要供测试使用。"""

        def delete(conn):
            conn.execute("DELETE FROM messages")

        await self.db.run(delete)

    @staticmethod
    def _row_to_message(row) -> dict[str, Any]:
        """将 SQLite row 还原为消息 dict。"""
        return {
            "role": row["role"],
            "content": row["content"],
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
        }
