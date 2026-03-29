"""Telegram bot setup and main polling loop."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from commandclaw.config import Settings
from commandclaw.telegram.handlers import create_message_handler

log = logging.getLogger(__name__)

_WELCOME = (
    "CommandClaw is online. Send me a message and the agent will handle it."
)


async def _start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Reply to the /start command with a welcome message."""
    if update.effective_chat is not None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=_WELCOME,
        )


def start_bot(
    agent_executor: Any,
    settings: Settings,
    cleanup_fn: Callable[[], Any],
) -> None:
    """Build the Telegram bot application and start polling.

    This is a blocking call — ``run_polling`` manages its own event loop.
    """
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()

    # /start greeting
    app.add_handler(CommandHandler("start", _start_command))

    # All non-command text messages go to the agent
    handler = create_message_handler(agent_executor, settings)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler))

    log.info("Starting Telegram polling…")
    try:
        app.run_polling(drop_pending_updates=True)
    finally:
        try:
            cleanup_fn()
        except Exception:
            log.exception("Error during cleanup")
