from __future__ import annotations

"""项目内 SQLite checkpoint store。

当前 LangGraph 仍使用 MemorySaver 编译图；本类持久化每次执行后的
`CheckpointSnapshot`，而不是完整 `AgentGraphState`。
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.config.settings import get_settings
from app.runtime.state_contracts import CheckpointSnapshot
from app.storage.sqlite import SQLiteDatabase

logger = logging.getLogger(__name__)


def build_checkpointer(settings=None):
    """Build the LangGraph-native checkpointer.

    The project currently ships LangGraph's in-memory saver by default. Some
    deployments may install the optional SQLite checkpointer package; when it is
    unavailable we explicitly fall back to MemorySaver while keeping
    SQLiteCheckpointStore as the project-level final checkpoint snapshot store.
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
    """按 thread_id 保存请求级 checkpoint snapshot。"""

    def __init__(self, db: SQLiteDatabase | None = None) -> None:
        """注入 SQLiteDatabase；未注入时使用默认 SQLITE_DB_PATH。"""
        self.db = db or SQLiteDatabase(get_settings().sqlite_db_path)

    async def save_snapshot(self, thread_id: str, snapshot: CheckpointSnapshot | dict[str, Any]) -> None:
        """保存指定 thread_id 的最新 checkpoint snapshot。"""
        model = snapshot if isinstance(snapshot, CheckpointSnapshot) else CheckpointSnapshot.model_validate(snapshot)
        payload = model.model_dump(mode="json")
        snapshot_json = json.dumps(payload, ensure_ascii=False, default=str)
        created_at = model.created_at or datetime.now(UTC).isoformat()
        updated_at = datetime.now(UTC).isoformat()

        def write(conn):
            conn.execute(
                """
                INSERT INTO graph_checkpoints(thread_id, schema_version, snapshot_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    snapshot_json = excluded.snapshot_json,
                    updated_at = excluded.updated_at
                """,
                (thread_id, model.schema_version, snapshot_json, created_at, updated_at),
            )

        await self.db.run(write)

    async def load_snapshot(self, thread_id: str) -> CheckpointSnapshot | None:
        """读取指定 thread_id 的 checkpoint snapshot。"""

        def read(conn):
            row = conn.execute(
                "SELECT snapshot_json FROM graph_checkpoints WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            return CheckpointSnapshot.model_validate(json.loads(row["snapshot_json"])) if row else None

        return await self.db.run(read)

    async def load(self, thread_id: str) -> dict[str, Any] | None:
        """Compatibility API returning the stored snapshot as a dict."""
        snapshot = await self.load_snapshot(thread_id)
        return snapshot.model_dump(mode="json") if snapshot else None

    async def clear(self) -> None:
        """清空 checkpoint 表，主要供测试使用。"""

        def delete(conn):
            conn.execute("DELETE FROM graph_checkpoints")

        await self.db.run(delete)
