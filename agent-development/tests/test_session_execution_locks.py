from __future__ import annotations

import asyncio

import pytest

from app.runtime.session_locks import SessionExecutionLockManager, SessionExecutionLockTimeout


@pytest.mark.asyncio
async def test_same_session_runs_serially_and_cleans_entry():
    manager = SessionExecutionLockManager(timeout_seconds=1)
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = False

    async def first():
        async with manager.lock("tenant:web:u1:s1"):
            first_entered.set()
            await release_first.wait()

    async def second():
        nonlocal second_entered
        await first_entered.wait()
        async with manager.lock("tenant:web:u1:s1"):
            second_entered = True

    first_task = asyncio.create_task(first())
    await first_entered.wait()
    second_task = asyncio.create_task(second())
    await asyncio.sleep(0.02)

    assert second_entered is False

    release_first.set()
    await asyncio.gather(first_task, second_task)

    assert second_entered is True
    assert manager.active_session_count() == 0


@pytest.mark.asyncio
async def test_different_sessions_can_run_concurrently():
    manager = SessionExecutionLockManager(timeout_seconds=1)
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = False

    async def first():
        async with manager.lock("tenant:web:u1:s1"):
            first_entered.set()
            await release_first.wait()

    async def second():
        nonlocal second_entered
        await first_entered.wait()
        async with manager.lock("tenant:web:u2:s1"):
            second_entered = True

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    await first_entered.wait()
    await asyncio.sleep(0.02)

    assert second_entered is True

    release_first.set()
    await asyncio.gather(first_task, second_task)
    assert manager.active_session_count() == 0


@pytest.mark.asyncio
async def test_lock_timeout_releases_waiter_reference():
    manager = SessionExecutionLockManager(timeout_seconds=0.01)
    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def first():
        async with manager.lock("tenant:web:u1:s1"):
            first_entered.set()
            await release_first.wait()

    first_task = asyncio.create_task(first())
    await first_entered.wait()

    with pytest.raises(SessionExecutionLockTimeout):
        async with manager.lock("tenant:web:u1:s1"):
            pass

    assert manager.active_session_count() == 1
    release_first.set()
    await first_task
    assert manager.active_session_count() == 0


@pytest.mark.asyncio
async def test_disabled_lock_does_not_serialize():
    manager = SessionExecutionLockManager(enabled=False, timeout_seconds=1)
    entered = 0

    async def task():
        nonlocal entered
        async with manager.lock("same-session"):
            entered += 1
            await asyncio.sleep(0.01)

    await asyncio.gather(task(), task())

    assert entered == 2
    assert manager.active_session_count() == 0
