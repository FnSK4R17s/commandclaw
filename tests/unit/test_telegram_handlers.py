"""Unit tests for telegram handler — lock-cache LRU + message dispatch."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from commandclaw.agent.context import AgentResult
from commandclaw.config import Settings
from commandclaw.telegram import handlers
from commandclaw.telegram.handlers import create_message_handler


@pytest.fixture(autouse=True)
def _reset_lock_cache():
    """Wipe the module-level lock cache around each test."""
    handlers._chat_locks.clear()
    yield
    handlers._chat_locks.clear()


def _make_settings(
    tmp_path: Path,
    allowed_ids: list[int] | None = None,
) -> Settings:
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    return Settings(
        vault_path=vault,
        agent_id="test",
        openai_api_key="sk-test",
        telegram_bot_token="tok",
        telegram_allowed_chat_ids=allowed_ids or [],
        mcp_gateway_url=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
        max_retries=0,
    )


def _make_update(chat_id: int = 100, text: str = "hello") -> MagicMock:
    update = MagicMock()
    update.effective_chat = SimpleNamespace(id=chat_id)
    update.message = SimpleNamespace(text=text)
    return update


def _make_context(agent=None) -> MagicMock:
    ctx = MagicMock()
    ctx.application.bot_data = {"agent": agent}
    ctx.bot = AsyncMock()
    return ctx


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


# ============================================================
# Handler dispatch — message routing through create_message_handler
# ============================================================


class TestHandlerDispatch:
    async def test_successful_response_sends_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        settings = _make_settings(tmp_path)
        mock_result = AgentResult(output="agent reply", success=True)
        monkeypatch.setattr(
            "commandclaw.telegram.handlers.invoke_agent",
            AsyncMock(return_value=mock_result),
        )

        handler = create_message_handler(settings)
        update = _make_update(chat_id=42, text="hi")
        ctx = _make_context(agent=MagicMock())

        await handler(update, ctx)
        ctx.bot.send_message.assert_called()

    async def test_failed_response_sends_error_alert(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        settings = _make_settings(tmp_path)
        mock_result = AgentResult(output="", success=False, error="something broke")
        monkeypatch.setattr(
            "commandclaw.telegram.handlers.invoke_agent",
            AsyncMock(return_value=mock_result),
        )

        handler = create_message_handler(settings)
        update = _make_update(chat_id=42, text="hi")
        ctx = _make_context(agent=MagicMock())

        await handler(update, ctx)
        ctx.bot.send_message.assert_called()
        call_text = ctx.bot.send_message.call_args_list[-1].kwargs.get(
            "text", ctx.bot.send_message.call_args_list[-1][1].get("text", "")
        )
        assert "something broke" in call_text

    async def test_no_effective_chat_is_noop(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        handler = create_message_handler(settings)
        update = MagicMock()
        update.effective_chat = None
        ctx = _make_context(agent=MagicMock())

        await handler(update, ctx)
        ctx.bot.send_message.assert_not_called()

    async def test_no_message_is_noop(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        handler = create_message_handler(settings)
        update = MagicMock()
        update.effective_chat = SimpleNamespace(id=1)
        update.message = None
        ctx = _make_context(agent=MagicMock())

        await handler(update, ctx)
        ctx.bot.send_message.assert_not_called()

    async def test_empty_text_is_noop(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        handler = create_message_handler(settings)
        update = _make_update(text="")
        ctx = _make_context(agent=MagicMock())

        await handler(update, ctx)
        ctx.bot.send_message.assert_not_called()

    async def test_unauthorised_chat_rejected(
        self, tmp_path: Path,
    ) -> None:
        settings = _make_settings(tmp_path, allowed_ids=[999])
        handler = create_message_handler(settings)
        update = _make_update(chat_id=42, text="hi")
        ctx = _make_context(agent=MagicMock())

        await handler(update, ctx)
        ctx.bot.send_message.assert_not_called()

    async def test_allowed_chat_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        settings = _make_settings(tmp_path, allowed_ids=[42])
        mock_result = AgentResult(output="ok", success=True)
        monkeypatch.setattr(
            "commandclaw.telegram.handlers.invoke_agent",
            AsyncMock(return_value=mock_result),
        )

        handler = create_message_handler(settings)
        update = _make_update(chat_id=42, text="hi")
        ctx = _make_context(agent=MagicMock())

        await handler(update, ctx)
        ctx.bot.send_message.assert_called()

    async def test_agent_not_ready_sends_alert(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        handler = create_message_handler(settings)
        update = _make_update(chat_id=42, text="hi")
        ctx = _make_context(agent=None)

        await handler(update, ctx)
        ctx.bot.send_message.assert_called()
        call_text = ctx.bot.send_message.call_args.kwargs.get(
            "text", ctx.bot.send_message.call_args[1].get("text", "")
        )
        assert "not ready" in call_text.lower()

    async def test_agent_exception_sends_error_alert(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        settings = _make_settings(tmp_path)
        monkeypatch.setattr(
            "commandclaw.telegram.handlers.invoke_agent",
            AsyncMock(side_effect=RuntimeError("kaboom")),
        )

        handler = create_message_handler(settings)
        update = _make_update(chat_id=42, text="hi")
        ctx = _make_context(agent=MagicMock())

        await handler(update, ctx)
        ctx.bot.send_message.assert_called()
        call_text = ctx.bot.send_message.call_args.kwargs.get(
            "text", ctx.bot.send_message.call_args[1].get("text", "")
        )
        assert "error" in call_text.lower()
