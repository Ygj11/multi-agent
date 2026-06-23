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
        """创建项目运行时使用的全部 SQLite 表及索引。"""
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
                    schema_version INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tool_execution_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT,
                    trace_id TEXT,
                    session_key TEXT,
                    agent_name TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    source TEXT,
                    server_name TEXT,
                    original_tool_name TEXT,
                    approval_id TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_tool_execution_logs_session
                ON tool_execution_logs(session_key, id);

                CREATE INDEX IF NOT EXISTS idx_tool_execution_logs_agent
                ON tool_execution_logs(agent_name);

                CREATE INDEX IF NOT EXISTS idx_tool_execution_logs_request
                ON tool_execution_logs(request_id);

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
                );

                CREATE INDEX IF NOT EXISTS idx_evidence_request
                ON evidence(request_id);

                CREATE INDEX IF NOT EXISTS idx_evidence_session
                ON evidence(session_key);

                CREATE TABLE IF NOT EXISTS approval_requests (
                    approval_id TEXT PRIMARY KEY,
                    external_approval_id TEXT,
                    session_key TEXT,
                    request_id TEXT,
                    trace_id TEXT,
                    thread_id TEXT,
                    checkpoint_id TEXT,
                    parent_approval_id TEXT,
                    root_approval_id TEXT,
                    approval_depth INTEGER NOT NULL DEFAULT 0,
                    next_approval_id TEXT,
                    approval_scope TEXT NOT NULL DEFAULT 'single_tool_call',
                    idempotency_key TEXT,
                    tenant_id TEXT,
                    subject TEXT,
                    user_id TEXT,
                    org_id TEXT,
                    org_path_json TEXT,
                    principal_snapshot_json TEXT,
                    auth_context_snapshot_json TEXT,
                    resource_type TEXT,
                    resource_id TEXT,
                    tool_required_scopes_json TEXT,
                    agent_name TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    callback_url TEXT,
                    resume_state_json TEXT NOT NULL,
                    pending_messages_json TEXT NOT NULL,
                    pending_tools_json TEXT NOT NULL,
                    pending_tool_call_json TEXT NOT NULL,
                    result_json TEXT,
                    final_answer TEXT,
                    error TEXT,
                    approver TEXT,
                    comment TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    decided_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_approval_requests_session
                ON approval_requests(session_key, created_at);

                CREATE INDEX IF NOT EXISTS idx_approval_requests_request
                ON approval_requests(request_id);

                CREATE TABLE IF NOT EXISTS approval_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    approval_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_approval_events_approval
                ON approval_events(approval_id, event_id);
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
