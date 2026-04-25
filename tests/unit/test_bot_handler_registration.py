"""Tests for PTB handler registration details in commandclaw.telegram.bot.

Verifies that:
1. The MessageHandler registered by _post_init has block=False so that
   invoke_agent runs as a background task and the /stop update can fire
   concurrently.
2. The /stop CommandHandler is registered at group=-1 (higher priority than
   the default group 0) so it is dispatched before any pending message handlers.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch, call


# ---------------------------------------------------------------------------
# Test 1 — MessageHandler must carry block=False
# ---------------------------------------------------------------------------


async def test_post_init_message_handler_has_block_false() -> None:
    """_post_init registers the TEXT MessageHandler with block=False so that
    incoming messages are dispatched as asyncio tasks, allowing /stop to fire
    concurrently while invoke_agent is running."""
    from telegram.ext import MessageHandler

    from commandclaw.telegram.bot import _post_init

    # Minimal Settings stub — only the fields _post_init touches.
    settings = MagicMock()
    settings.queue_cap = 10
    settings.discard_ttl_seconds = 60

    # Application stub — captures add_handler calls.
    application = MagicMock()
    application.bot_data = {"settings": settings}
    application.add_handler = MagicMock()

    fake_agent = MagicMock()
    fake_mcp_client = MagicMock()
    fake_saver = MagicMock()

    async def fake_close():
        pass

    with (
        patch(
            "commandclaw.telegram.bot.open_checkpointer",
            new=AsyncMock(return_value=(fake_saver, fake_close)),
        ),
        patch(
            "commandclaw.telegram.bot.build_agent_graph",
            new=AsyncMock(return_value=(fake_agent, fake_mcp_client)),
        ),
        patch("commandclaw.telegram.bot.create_process_fn_factory", return_value=MagicMock()),
        patch("commandclaw.telegram.bot.Dispatcher"),
        patch("commandclaw.telegram.bot.create_message_handler", return_value=AsyncMock()),
    ):
        await _post_init(application)

    # Find the MessageHandler among all add_handler calls.
    msg_handler_calls = [
        c for c in application.add_handler.call_args_list
        if isinstance(c.args[0], MessageHandler)
    ]
    assert msg_handler_calls, "add_handler was never called with a MessageHandler"

    registered_handler: MessageHandler = msg_handler_calls[0].args[0]
    assert registered_handler.block is False, (
        f"MessageHandler.block expected False (non-blocking / task-based dispatch), "
        f"got {registered_handler.block!r}. "
        "Set block=False so invoke_agent runs as an asyncio.create_task() and /stop "
        "can fire concurrently."
    )


# ---------------------------------------------------------------------------
# Test 2 — /stop CommandHandler must be in group=-1
# ---------------------------------------------------------------------------


def test_start_bot_stop_handler_registered_in_group_negative_one() -> None:
    """/stop CommandHandler must be registered in group=-1 so it receives higher
    dispatch priority than group-0 message handlers and can interrupt an
    ongoing invoke_agent session."""
    from telegram.ext import CommandHandler

    from commandclaw.telegram.bot import start_bot

    # Settings stub — only the field start_bot touches directly.
    settings = MagicMock()
    settings.telegram_bot_token = "fake-token"

    # Capture all add_handler calls before run_polling would block forever.
    add_handler_calls: list[tuple] = []

    fake_app = MagicMock()
    fake_app.bot_data = {}
    fake_app.add_handler = MagicMock(side_effect=lambda *a, **kw: add_handler_calls.append((a, kw)))
    fake_app.run_polling = MagicMock()  # prevent actual polling

    fake_builder = MagicMock()
    fake_builder.token.return_value = fake_builder
    fake_builder.post_init.return_value = fake_builder
    fake_builder.post_shutdown.return_value = fake_builder
    fake_builder.build.return_value = fake_app

    with patch("commandclaw.telegram.bot.ApplicationBuilder", return_value=fake_builder):
        start_bot(settings)

    # Find calls where the first positional arg is a CommandHandler for "stop".
    stop_calls = [
        (args, kwargs)
        for args, kwargs in add_handler_calls
        if args and isinstance(args[0], CommandHandler) and "stop" in args[0].commands
    ]
    assert stop_calls, (
        "add_handler was never called with a CommandHandler for 'stop'. "
        "Expected start_bot to register CommandHandler('stop', ...) with group=-1."
    )

    args, kwargs = stop_calls[0]
    # group can be passed positionally (index 1) or as a keyword.
    if len(args) >= 2:
        group = args[1]
    else:
        group = kwargs.get("group", 0)  # PTB default group is 0

    assert group == -1, (
        f"/stop CommandHandler registered at group={group!r}, expected group=-1. "
        "group=-1 gives it dispatch priority over group-0 message handlers so it "
        "can interrupt an active invoke_agent call."
    )
