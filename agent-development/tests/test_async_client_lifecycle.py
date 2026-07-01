import asyncio

import pytest

from app.runtime.async_client_lifecycle import AsyncClientLifecycle, AsyncClientLifecycleClosedError


class FakeClient:
    def __init__(self):
        self.is_closed = False
        self.close_calls = 0

    async def aclose(self):
        self.close_calls += 1
        self.is_closed = True


class MethodClosedClient:
    def __init__(self):
        self.closed = False

    def is_closed(self):
        return self.closed

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_concurrent_first_leases_create_exactly_one_client():
    created = []
    lifecycle = AsyncClientLifecycle(
        factory=lambda: created.append(FakeClient()) or created[-1],
        close_client=lambda client: client.aclose(),
    )

    async def use_client():
        async with lifecycle.lease() as client:
            await asyncio.sleep(0)
            return client

    clients = await asyncio.gather(*(use_client() for _ in range(20)))

    assert len(created) == 1
    assert all(client is created[0] for client in clients)


@pytest.mark.asyncio
async def test_close_waits_for_active_lease_without_serializing_request_work():
    created = []
    lifecycle = AsyncClientLifecycle(
        factory=lambda: created.append(FakeClient()) or created[-1],
        close_client=lambda client: client.aclose(),
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold_lease():
        async with lifecycle.lease():
            entered.set()
            await release.wait()

    request_task = asyncio.create_task(hold_lease())
    await entered.wait()
    close_task = asyncio.create_task(lifecycle.close())
    await asyncio.sleep(0)

    assert created[0].close_calls == 0
    release.set()
    await request_task
    await close_task

    assert created[0].close_calls == 1
    assert lifecycle.closed is True


@pytest.mark.asyncio
async def test_close_is_idempotent_and_never_recreates_after_close():
    created = []
    lifecycle = AsyncClientLifecycle(
        factory=lambda: created.append(FakeClient()) or created[-1],
        close_client=lambda client: client.aclose(),
    )

    await lifecycle.close()
    await lifecycle.close()

    assert created == []
    with pytest.raises(AsyncClientLifecycleClosedError):
        await lifecycle.get_client_for_testing()


@pytest.mark.asyncio
async def test_external_client_is_not_closed_without_explicit_ownership_transfer():
    external = FakeClient()
    lifecycle = AsyncClientLifecycle(
        factory=FakeClient,
        close_client=lambda client: client.aclose(),
        client=external,
    )

    await lifecycle.close()

    assert external.close_calls == 0
    with pytest.raises(AsyncClientLifecycleClosedError):
        await lifecycle.get_client_for_testing()


@pytest.mark.asyncio
async def test_explicitly_transferred_client_is_closed_once():
    external = FakeClient()
    lifecycle = AsyncClientLifecycle(
        factory=FakeClient,
        close_client=lambda client: client.aclose(),
        client=external,
        owns_client=True,
    )

    await asyncio.gather(lifecycle.close(), lifecycle.close())

    assert external.close_calls == 1


@pytest.mark.asyncio
async def test_is_closed_method_is_called_instead_of_treated_as_truthy():
    created = []
    lifecycle = AsyncClientLifecycle(
        factory=lambda: created.append(MethodClosedClient()) or created[-1],
        close_client=lambda client: client.aclose(),
    )

    async with lifecycle.lease() as first:
        assert first.closed is False

    async with lifecycle.lease() as second:
        assert second is first
