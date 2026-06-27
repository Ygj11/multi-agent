from __future__ import annotations

"""同一会话串行执行锁。

本模块只提供进程内锁：它保证单个 AppContainer / Uvicorn worker 内同一
session_key 的 Graph run 串行，不同 session_key 仍可并发。多 worker 或多实例
部署需要 Redis、数据库 advisory lock 或队列分区等分布式方案。
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from time import monotonic


class SessionExecutionLockTimeout(TimeoutError):
    """等待同一会话上一条请求完成超时。"""

    def __init__(self, session_key: str, timeout_seconds: float) -> None:
        self.session_key = session_key
        self.timeout_seconds = timeout_seconds
        super().__init__(f"session_busy_timeout:{session_key}:{timeout_seconds}")


@dataclass(slots=True)
class _SessionLockEntry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    ref_count: int = 0
    last_used_at: float = field(default_factory=monotonic)


class SessionExecutionLockManager:
    """按 session_key 管理异步锁。

    `ref_count` 同时统计等待者和持有者。请求结束或等待超时后会递减；
    归零时删除 entry，避免本地进程长时间运行后积累无限 session lock。
    """

    def __init__(self, *, enabled: bool = True, timeout_seconds: float = 60.0) -> None:
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds
        self._guard = asyncio.Lock()
        self._entries: dict[str, _SessionLockEntry] = {}

    @asynccontextmanager
    async def lock(self, session_key: str) -> AsyncIterator[None]:
        """获取指定 session 的串行执行权。

        锁只保护 Graph run 的进入顺序；具体业务、LLM 和工具调用仍在锁持有期内
        正常异步执行。不同 session_key 使用不同锁，不互相阻塞。
        """
        if not self.enabled or not session_key:
            yield
            return

        entry = await self._reserve(session_key)
        acquired = False
        try:
            await asyncio.wait_for(entry.lock.acquire(), timeout=self.timeout_seconds)
            acquired = True
            entry.last_used_at = monotonic()
            yield
        except TimeoutError as exc:
            raise SessionExecutionLockTimeout(session_key, self.timeout_seconds) from exc
        finally:
            if acquired:
                entry.lock.release()
            await self._release(session_key, entry)

    async def _reserve(self, session_key: str) -> _SessionLockEntry:
        async with self._guard:
            entry = self._entries.get(session_key)
            if entry is None:
                entry = _SessionLockEntry()
                self._entries[session_key] = entry
            entry.ref_count += 1
            entry.last_used_at = monotonic()
            return entry

    async def _release(self, session_key: str, entry: _SessionLockEntry) -> None:
        async with self._guard:
            current = self._entries.get(session_key)
            if current is not entry:
                return
            entry.ref_count = max(0, entry.ref_count - 1)
            entry.last_used_at = monotonic()
            if entry.ref_count == 0 and not entry.lock.locked():
                self._entries.pop(session_key, None)

    def active_session_count(self) -> int:
        """返回当前仍有持有者或等待者的 session 数，供测试和诊断使用。"""
        return len(self._entries)
