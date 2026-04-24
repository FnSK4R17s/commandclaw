"""Unit tests for telegram handler helpers — lock-cache LRU bound."""

from __future__ import annotations

import asyncio

import pytest

from commandclaw.telegram import handlers


@pytest.fixture(autouse=True)
def _reset_lock_cache():
    """Wipe the module-level lock cache around each test."""
    handlers._chat_locks.clear()
    yield
    handlers._chat_locks.clear()


def test_lock_for_returns_same_lock_for_same_chat() -> None:
    a = handlers._lock_for(42)
    b = handlers._lock_for(42)
    assert a is b


def test_lock_for_returns_distinct_locks_per_chat() -> None:
    assert handlers._lock_for(1) is not handlers._lock_for(2)


def test_lock_cache_evicts_oldest_past_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handlers, "_MAX_CHAT_LOCKS", 4)

    for chat_id in range(4):
        handlers._lock_for(chat_id)
    assert list(handlers._chat_locks) == [0, 1, 2, 3]

    handlers._lock_for(4)  # pushes out chat 0
    assert list(handlers._chat_locks) == [1, 2, 3, 4]
    assert 0 not in handlers._chat_locks


def test_lock_cache_promotes_on_reuse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handlers, "_MAX_CHAT_LOCKS", 3)

    for chat_id in (1, 2, 3):
        handlers._lock_for(chat_id)
    handlers._lock_for(1)  # reuse — should move 1 to the tail
    handlers._lock_for(4)  # evicts the now-oldest (2)

    assert 2 not in handlers._chat_locks
    assert 1 in handlers._chat_locks


async def test_lock_cache_respects_actual_locking() -> None:
    lock = handlers._lock_for(7)
    held = asyncio.Event()
    released = asyncio.Event()

    async def holder() -> None:
        async with lock:
            held.set()
            await released.wait()

    async def waiter() -> bool:
        await held.wait()
        second = handlers._lock_for(7)
        assert second is lock
        locked_immediately = second.locked()
        released.set()
        return locked_immediately

    h_task = asyncio.create_task(holder())
    try:
        assert await asyncio.wait_for(waiter(), timeout=1.0) is True
    finally:
        await h_task
