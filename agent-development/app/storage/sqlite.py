from __future__ import annotations

"""SQLite 轻量封装。

第二阶段使用 Python 标准库 sqlite3，不引入 ORM。每个操作使用独立连接，
并通过 asyncio.to_thread 让现有 async 接口保持不变。
"""

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class SQLiteDatabase:
    """负责 SQLite 文件路径、初始化和线程化执行。"""

    def __init__(self, db_path: str | Path) -> None:
        """初始化数据库路径并幂等创建表结构。"""
        self.path = Path(db_path)
        if not self.path.is_absolute():
            self.path = Path.cwd() / self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        """创建第二阶段需要的 messages、short_term_memory、graph_checkpoints 表。"""
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_key TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_created
                ON messages(session_key, created_at);

                CREATE TABLE IF NOT EXISTS short_term_memory (
                    session_key TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS graph_checkpoints (
                    thread_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tool_call_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT,
                    trace_id TEXT,
                    session_key TEXT,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    allowed INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tool_call_logs_session_created
                ON tool_call_logs(session_key, created_at);

                CREATE INDEX IF NOT EXISTS idx_tool_call_logs_trace
                ON tool_call_logs(trace_id);

                CREATE INDEX IF NOT EXISTS idx_tool_call_logs_request
                ON tool_call_logs(request_id);
                """
            )

    def connect(self) -> sqlite3.Connection:
        """创建 SQLite 连接，并返回 dict-like row。"""
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    async def run(self, func: Callable[[sqlite3.Connection], T]) -> T:
        """在线程池中执行同步 sqlite3 操作。"""
        return await asyncio.to_thread(self._run_sync, func)

    def _run_sync(self, func: Callable[[sqlite3.Connection], T]) -> T:
        """同步执行数据库操作并提交事务。"""
        with self.connect() as conn:
            result = func(conn)
            conn.commit()
            return result
