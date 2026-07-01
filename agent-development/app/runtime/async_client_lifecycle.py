from __future__ import annotations

"""长期异步 client 的所有权、并发借用与关闭生命周期。"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Generic, TypeVar


TClient = TypeVar("TClient")


class AsyncClientLifecycleClosedError(RuntimeError):
    """调用方尝试使用已关闭或正在关闭的长期 client。"""


class AsyncClientLifecycle(Generic[TClient]):
    """为一个长期 client 提供明确所有权和非串行化的并发关闭保护。

    `lease()` 只在借用和归还时持锁，实际网络请求在锁外执行。组件自行创建
    client 时拥有关闭权；外部注入 client 默认由调用方拥有，可显式转移所有权。
    """

    def __init__(
        self,
        *,
        factory: Callable[[], TClient],
        close_client: Callable[[TClient], Awaitable[None]],
        client: TClient | None = None,
        owns_client: bool = False,
        is_client_closed: Callable[[TClient], bool] | None = None,
    ) -> None:
        self._factory = factory
        self._close_client = close_client
        self._client = client
        self._owns_client = client is None or owns_client
        self._is_client_closed = is_client_closed or self._default_is_client_closed
        self._lock = asyncio.Lock()
        self._idle = asyncio.Event()
        self._idle.set()
        self._close_complete = asyncio.Event()
        self._close_complete.set()
        self._active_leases = 0
        self._closing = False
        self._closed = False

    @property
    def client(self) -> TClient | None:
        """返回当前 client，仅用于诊断或测试；业务请求应使用 lease()。"""
        return self._client

    @property
    def closed(self) -> bool:
        return self._closed

    @asynccontextmanager
    async def lease(self) -> AsyncIterator[TClient]:
        """借用一个 client；关闭时会等待所有已借出的请求归还。"""
        async with self._lock:
            client = self._get_or_create_locked()
            self._active_leases += 1
            self._idle.clear()
        try:
            yield client
        finally:
            async with self._lock:
                self._active_leases -= 1
                if self._active_leases == 0:
                    self._idle.set()

    async def get_client_for_testing(self) -> TClient:
        """返回 client 供断言使用；生产调用必须使用 lease()。"""
        async with self._lock:
            return self._get_or_create_locked()

    async def close(self) -> None:
        """幂等关闭，并等待进行中的请求完成后再释放自有 client。"""
        wait_for_existing_close = False
        client: TClient | None = None
        owns_client = False
        async with self._lock:
            if self._closed:
                return
            if self._closing:
                wait_for_existing_close = True
            else:
                self._closing = True
                self._close_complete.clear()
                client = self._client
                owns_client = self._owns_client

        if wait_for_existing_close:
            await self._close_complete.wait()
            return

        close_error: BaseException | None = None
        try:
            await self._idle.wait()
            if client is not None and owns_client:
                await self._close_client(client)
        except BaseException as exc:
            close_error = exc
        finally:
            async with self._lock:
                self._client = None
                self._closed = True
                self._closing = False
                self._close_complete.set()

        if close_error is not None:
            raise close_error

    def _get_or_create_locked(self) -> TClient:
        # 关闭或正在关闭时禁止静默重建 client。Container shutdown 后如果还有请求进来，
        # 应明确失败，而不是偷偷创建一个无人关闭的新连接池。
        if self._closed:
            raise AsyncClientLifecycleClosedError("client lifecycle is closed")
        if self._closing:
            raise AsyncClientLifecycleClosedError("client lifecycle is closing")
        if self._client is None:
            self._client = self._factory()
            self._owns_client = True
            return self._client
        if self._is_client_closed(self._client):
            if self._owns_client:
                raise AsyncClientLifecycleClosedError("owned client was closed outside its lifecycle")
            raise AsyncClientLifecycleClosedError("injected client was closed by its owner")
        return self._client

    @staticmethod
    def _default_is_client_closed(value: Any) -> bool:
        """兼容 is_closed 布尔属性和 is_closed() 方法两种 client API。"""
        marker = getattr(value, "is_closed", False)
        if callable(marker):
            return bool(marker())
        return bool(marker)
