"""Unit tests for Telegram bot command handlers: /stop, /discarded, /recover."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from commandclaw.telegram.bot import _discarded_command, _recover_command, _stop_command


def _make_update(chat_id: int = 42, args: list[str] | None = None) -> MagicMock:
    update = MagicMock()
    update.effective_chat = SimpleNamespace(id=chat_id)
    return update


def _make_context(dispatcher=None, args: list[str] | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.application.bot_data = {}
    if dispatcher is not None:
        ctx.application.bot_data["dispatcher"] = dispatcher
    ctx.bot = AsyncMock()
    ctx.args = args or []
    return ctx


def _make_dispatcher(abort_return: int = 0) -> MagicMock:
    dispatcher = MagicMock()
    dispatcher.abort = AsyncMock(return_value=abort_return)
    dispatcher.get_discard_queue = MagicMock()
    dispatcher.dispatch = AsyncMock()
    return dispatcher


# ============================================================
# /stop command
# ============================================================


class TestStopCommand:
    async def test_stop_aborts_session_and_sends_confirmation(self) -> None:
        """User sends /stop — bot aborts session and replies with count of moved messages."""
        dispatcher = _make_dispatcher(abort_return=3)
        update = _make_update(chat_id=42)
        ctx = _make_context(dispatcher=dispatcher)

        await _stop_command(update, ctx)

        dispatcher.abort.assert_called_once_with("42")
        ctx.bot.send_message.assert_called_once()
        text: str = ctx.bot.send_message.call_args.kwargs.get(
            "text", ctx.bot.send_message.call_args[1].get("text", "")
        )
        assert "stopped" in text.lower(), f"Expected 'stopped' in reply, got: {text!r}"
        assert "3" in text, f"Expected move count '3' in reply, got: {text!r}"


# ============================================================
# /discarded command
# ============================================================


class TestDiscardedCommand:
    async def test_discarded_lists_messages_with_indices(self) -> None:
        """User sends /discarded — bot replies listing each envelope content with 1-based index."""
        from commandclaw.message.envelope import MsgEnvelope

        env_a = MsgEnvelope(session_id="42", content="first message", message_type="user")
        env_b = MsgEnvelope(session_id="42", content="second message", message_type="user")

        discard_queue = MagicMock()
        discard_queue.list_discarded = MagicMock(return_value=[env_a, env_b])

        dispatcher = _make_dispatcher()
        dispatcher.get_discard_queue = MagicMock(return_value=discard_queue)

        update = _make_update(chat_id=42)
        ctx = _make_context(dispatcher=dispatcher)

        await _discarded_command(update, ctx)

        dispatcher.get_discard_queue.assert_called_once_with("42")
        discard_queue.list_discarded.assert_called_once()
        ctx.bot.send_message.assert_called_once()
        text: str = ctx.bot.send_message.call_args.kwargs.get(
            "text", ctx.bot.send_message.call_args[1].get("text", "")
        )
        assert "1." in text, f"Expected '1.' (1-indexed) in reply, got: {text!r}"
        assert "2." in text, f"Expected '2.' (1-indexed) in reply, got: {text!r}"
        assert "first message" in text, f"Expected envelope content in reply, got: {text!r}"
        assert "second message" in text, f"Expected envelope content in reply, got: {text!r}"


# ============================================================
# /recover command
# ============================================================


class TestRecoverCommand:
    async def test_recover_specific_index_requeues_message(self) -> None:
        """User sends /recover 2 — bot recovers 0-indexed item 1 and re-dispatches it."""
        from commandclaw.message.envelope import MsgEnvelope

        recovered_env = MsgEnvelope(session_id="42", content="recover me", message_type="user")

        discard_queue = MagicMock()
        discard_queue.recover = MagicMock(return_value=recovered_env)

        dispatcher = _make_dispatcher()
        dispatcher.get_discard_queue = MagicMock(return_value=discard_queue)

        update = _make_update(chat_id=42)
        ctx = _make_context(dispatcher=dispatcher, args=["2"])

        await _recover_command(update, ctx)

        dispatcher.get_discard_queue.assert_called_once_with("42")
        # User supplied "2" (1-indexed) → internally recover(1) (0-indexed)
        discard_queue.recover.assert_called_once_with(1)
        dispatcher.dispatch.assert_called_once_with(recovered_env)
        ctx.bot.send_message.assert_called_once()

    async def test_recover_all_requeues_all_messages(self) -> None:
        """User sends /recover all — bot recovers every discarded message and re-dispatches each."""
        from commandclaw.message.envelope import MsgEnvelope

        env_a = MsgEnvelope(session_id="42", content="alpha", message_type="user")
        env_b = MsgEnvelope(session_id="42", content="beta", message_type="user")

        discard_queue = MagicMock()
        discard_queue.recover_all = MagicMock(return_value=[env_a, env_b])

        dispatcher = _make_dispatcher()
        dispatcher.get_discard_queue = MagicMock(return_value=discard_queue)

        update = _make_update(chat_id=42)
        ctx = _make_context(dispatcher=dispatcher, args=["all"])

        await _recover_command(update, ctx)

        dispatcher.get_discard_queue.assert_called_once_with("42")
        discard_queue.recover_all.assert_called_once()
        assert dispatcher.dispatch.call_count == 2, (
            f"Expected dispatch called twice (once per envelope), got {dispatcher.dispatch.call_count}"
        )
        dispatched = [call.args[0] for call in dispatcher.dispatch.call_args_list]
        assert env_a in dispatched
        assert env_b in dispatched
        ctx.bot.send_message.assert_called_once()
