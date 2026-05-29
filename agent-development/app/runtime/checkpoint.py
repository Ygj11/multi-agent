from __future__ import annotations

"""项目内 SQLite checkpoint store。

当前 LangGraph 仍使用 MemorySaver 编译图；本类持久化每次执行后的最终 state，
作为第二阶段的 checkpoint 抽象和后续替换官方 SQLite/PostgreSQL checkpointer 的接入点。
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.config.settings import get_settings
from app.storage.sqlite import SQLiteDatabase

logger = logging.getLogger(__name__)


def build_checkpointer(settings=None):
    """Build the LangGraph-native checkpointer.

    The project currently ships LangGraph's in-memory saver by default. Some
    deployments may install the optional SQLite checkpointer package; when it is
    unavailable we explicitly fall back to MemorySaver while keeping
    SQLiteCheckpointStore as the project-level final state snapshot store.
    """
    from langgraph.checkpoint.memory import MemorySaver

    settings = settings or get_settings()
    backend = (getattr(settings, "checkpoint_backend", "memory") or "memory").lower()
    if backend == "memory":
        return MemorySaver()
    if backend == "sqlite":
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on optional package
            logger.warning(
                "LangGraph SQLite checkpointer is not installed; falling back to MemorySaver. "
                "SQLiteCheckpointStore still persists final state snapshots. error=%s",
                exc,
            )
            return MemorySaver()

        db_path = getattr(settings, "checkpoint_db_path", None) or getattr(settings, "sqlite_db_path", None)
        return AsyncSqliteSaver.from_conn_string(str(db_path))
    raise ValueError(f"unsupported_checkpoint_backend:{backend}")


class SQLiteCheckpointStore:
    """按 thread_id/session_key 保存 LangGraph 最终 state。"""

    def __init__(self, db: SQLiteDatabase | None = None) -> None:
        """注入 SQLiteDatabase；未注入时使用默认 SQLITE_DB_PATH。"""
        self.db = db or SQLiteDatabase(get_settings().sqlite_db_path)

    async def save(self, thread_id: str, state: dict[str, Any]) -> None:
        """保存指定 thread_id 的最新图状态。"""
        state_json = json.dumps(state, ensure_ascii=False, default=str)
        updated_at = datetime.now(UTC).isoformat()

        def write(conn):
            conn.execute(
                """
                INSERT INTO graph_checkpoints(thread_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (thread_id, state_json, updated_at),
            )

        await self.db.run(write)

    async def load(self, thread_id: str) -> dict[str, Any] | None:
        """读取指定 thread_id 的最新图状态。"""

        def read(conn):
            row = conn.execute(
                "SELECT state_json FROM graph_checkpoints WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            return json.loads(row["state_json"]) if row else None

        return await self.db.run(read)

    async def clear(self) -> None:
        """清空 checkpoint 表，主要供测试使用。"""

        def delete(conn):
            conn.execute("DELETE FROM graph_checkpoints")

        await self.db.run(delete)
