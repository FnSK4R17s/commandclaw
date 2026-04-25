"""Unit tests for telegram handler — message dispatch via Dispatcher."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from commandclaw.config import Settings
from commandclaw.telegram.handlers import create_message_handler


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


# ============================================================
# Handler dispatch — message routing through create_message_handler
# ============================================================


class TestHandlerDispatch:
    async def test_successful_response_sends_message(
        self, tmp_path: Path,
    ) -> None:
        settings = _make_settings(tmp_path)
        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock()

        handler = create_message_handler(settings)
        update = _make_update(chat_id=42, text="hi")
        ctx = _make_context_with_dispatcher(dispatcher=mock_dispatcher)

        await handler(update, ctx)
        mock_dispatcher.dispatch.assert_called_once()

    async def test_failed_response_sends_error_alert(
        self, tmp_path: Path,
    ) -> None:
        settings = _make_settings(tmp_path)
        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock(side_effect=RuntimeError("something broke"))

        handler = create_message_handler(settings)
        update = _make_update(chat_id=42, text="hi")
        ctx = _make_context_with_dispatcher(dispatcher=mock_dispatcher)

        await handler(update, ctx)
        ctx.bot.send_message.assert_called()
        call_text = ctx.bot.send_message.call_args_list[-1].kwargs.get(
            "text", ctx.bot.send_message.call_args_list[-1][1].get("text", "")
        )
        assert "error" in call_text.lower()

    async def test_no_effective_chat_is_noop(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        handler = create_message_handler(settings)
        update = MagicMock()
        update.effective_chat = None
        ctx = _make_context_with_dispatcher()

        await handler(update, ctx)
        ctx.bot.send_message.assert_not_called()

    async def test_no_message_is_noop(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        handler = create_message_handler(settings)
        update = MagicMock()
        update.effective_chat = SimpleNamespace(id=1)
        update.message = None
        ctx = _make_context_with_dispatcher()

        await handler(update, ctx)
        ctx.bot.send_message.assert_not_called()

    async def test_empty_text_is_noop(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        handler = create_message_handler(settings)
        update = _make_update(text="")
        ctx = _make_context_with_dispatcher()

        await handler(update, ctx)
        ctx.bot.send_message.assert_not_called()

    async def test_unauthorised_chat_rejected(
        self, tmp_path: Path,
    ) -> None:
        settings = _make_settings(tmp_path, allowed_ids=[999])
        handler = create_message_handler(settings)
        update = _make_update(chat_id=42, text="hi")
        ctx = _make_context_with_dispatcher()

        await handler(update, ctx)
        ctx.bot.send_message.assert_not_called()

    async def test_allowed_chat_passes(
        self, tmp_path: Path,
    ) -> None:
        settings = _make_settings(tmp_path, allowed_ids=[42])
        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock()

        handler = create_message_handler(settings)
        update = _make_update(chat_id=42, text="hi")
        ctx = _make_context_with_dispatcher(dispatcher=mock_dispatcher)

        await handler(update, ctx)
        mock_dispatcher.dispatch.assert_called_once()

    async def test_agent_not_ready_sends_alert(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        handler = create_message_handler(settings)
        update = _make_update(chat_id=42, text="hi")
        ctx = _make_context_with_dispatcher(dispatcher=None)

        await handler(update, ctx)
        ctx.bot.send_message.assert_called()
        call_text = ctx.bot.send_message.call_args.kwargs.get(
            "text", ctx.bot.send_message.call_args[1].get("text", "")
        )
        assert "not ready" in call_text.lower()

    async def test_agent_exception_sends_error_alert(
        self, tmp_path: Path,
    ) -> None:
        settings = _make_settings(tmp_path)
        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock(side_effect=RuntimeError("kaboom"))

        handler = create_message_handler(settings)
        update = _make_update(chat_id=42, text="hi")
        ctx = _make_context_with_dispatcher(dispatcher=mock_dispatcher)

        await handler(update, ctx)
        ctx.bot.send_message.assert_called()
        call_text = ctx.bot.send_message.call_args.kwargs.get(
            "text", ctx.bot.send_message.call_args[1].get("text", "")
        )
        assert "error" in call_text.lower()


# ============================================================
# Dispatcher-based handler — new behavior under message-queue feature
# ============================================================


def _make_context_with_dispatcher(dispatcher=None) -> MagicMock:
    ctx = MagicMock()
    ctx.application.bot_data = {}
    if dispatcher is not None:
        ctx.application.bot_data["dispatcher"] = dispatcher
    ctx.bot = AsyncMock()
    return ctx


class TestDispatcherBasedHandler:
    async def test_handler_dispatches_envelope_to_dispatcher(
        self, tmp_path: Path,
    ) -> None:
        from commandclaw.message.envelope import MsgEnvelope

        settings = _make_settings(tmp_path)
        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock()

        handler = create_message_handler(settings)
        update = _make_update(chat_id=55, text="queue me")
        ctx = _make_context_with_dispatcher(dispatcher=mock_dispatcher)

        await handler(update, ctx)

        mock_dispatcher.dispatch.assert_called_once()
        envelope: MsgEnvelope = mock_dispatcher.dispatch.call_args[0][0]
        assert isinstance(envelope, MsgEnvelope)
        assert envelope.session_id == "55"
        assert envelope.content == "queue me"
        assert envelope.message_type == "user"

    async def test_handler_with_no_dispatcher_sends_error(
        self, tmp_path: Path,
    ) -> None:
        """When bot_data has an agent but no dispatcher, handler must send an error.

        The new handler looks for bot_data["dispatcher"] — a stale bot_data that
        only carries "agent" (the old key) must be treated as not-ready.
        """
        settings = _make_settings(tmp_path)
        handler = create_message_handler(settings)
        update = _make_update(chat_id=55, text="queue me")
        # Simulate old-style bot_data: agent present, dispatcher absent.
        ctx = MagicMock()
        ctx.application.bot_data = {"agent": MagicMock()}  # old key, no dispatcher
        ctx.bot = AsyncMock()

        await handler(update, ctx)

        ctx.bot.send_message.assert_called()
        call_text = ctx.bot.send_message.call_args.kwargs.get(
            "text", ctx.bot.send_message.call_args[1].get("text", "")
        )
        assert "not ready" in call_text.lower()
