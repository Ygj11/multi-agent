from __future__ import annotations

"""未来 checkpoint backend 示例。"""

from typing import Any


class PostgreSQLCheckpointBackendExample:
    """未来替换 SQLiteCheckpointStore 的 PostgreSQL 示例，默认不连接。"""

    def __init__(self, dsn: str | None = None) -> None:
        # TODO: 接真实 PostgreSQL 连接池、事务、序列化、并发控制和迁移脚本。
        self.dsn = dsn

    async def save(self, thread_id: str, state: dict[str, Any], request_id: str | None = None, trace_id: str | None = None) -> None:
        if not self.dsn:
            raise RuntimeError("PostgreSQL checkpoint DSN is not configured; real backend is disabled by default.")
        # TODO: INSERT ... ON CONFLICT(thread_id) DO UPDATE。

    async def load(self, thread_id: str, request_id: str | None = None, trace_id: str | None = None) -> dict[str, Any] | None:
        if not self.dsn:
            raise RuntimeError("PostgreSQL checkpoint DSN is not configured; real backend is disabled by default.")
        # TODO: SELECT state_json FROM checkpoints WHERE thread_id = ...
        return None


class RedisCheckpointBackendExample:
    """未来替换 SQLiteCheckpointStore 的 Redis 示例，默认不连接。"""

    def __init__(self, redis_url: str | None = None) -> None:
        # TODO: 接真实 Redis client、TTL、序列化、并发控制和持久化策略。
        self.redis_url = redis_url

    async def save(self, thread_id: str, state: dict[str, Any], request_id: str | None = None, trace_id: str | None = None) -> None:
        if not self.redis_url:
            raise RuntimeError("Redis checkpoint URL is not configured; real backend is disabled by default.")
        # TODO: SET checkpoint:{thread_id} state_json。

    async def load(self, thread_id: str, request_id: str | None = None, trace_id: str | None = None) -> dict[str, Any] | None:
        if not self.redis_url:
            raise RuntimeError("Redis checkpoint URL is not configured; real backend is disabled by default.")
        # TODO: GET checkpoint:{thread_id}。
        return None

