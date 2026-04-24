"""Telegram bot setup — builds the agent inside the PTB event loop."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from commandclaw.agent.graph import build_agent_graph
from commandclaw.agent.persistence import open_checkpointer
from commandclaw.config import Settings
from commandclaw.telegram.handlers import create_message_handler

log = logging.getLogger(__name__)

_WELCOME = "CommandClaw is online. Send me a message and the agent will handle it."

# Stored on Application.bot_data so handlers + lifecycle hooks share state.
_BOT_DATA_AGENT = "agent"
_BOT_DATA_SETTINGS = "settings"
_BOT_DATA_MCP_CLIENT = "mcp_client"
_BOT_DATA_CHECKPOINTER_CLOSE = "checkpointer_close"


async def _start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Reply to /start with a welcome message."""
    if update.effective_chat is not None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=_WELCOME,
        )


async def _post_init(application: Application) -> None:
    """Build the agent + checkpointer inside PTB's running event loop."""
    settings: Settings = application.bot_data[_BOT_DATA_SETTINGS]

    saver, close_checkpointer = await open_checkpointer(settings)
    agent, mcp_client = await build_agent_graph(settings, checkpointer=saver)

    application.bot_data[_BOT_DATA_AGENT] = agent
    application.bot_data[_BOT_DATA_MCP_CLIENT] = mcp_client
    application.bot_data[_BOT_DATA_CHECKPOINTER_CLOSE] = close_checkpointer

    handler = create_message_handler(settings)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler))
    log.info("Agent + handler wired into Telegram application")


async def _post_shutdown(application: Application) -> None:
    """Async teardown: MCP disconnect, checkpointer close, Langfuse flush."""
    from commandclaw.tracing.langfuse_tracing import flush_tracing

    mcp_client = application.bot_data.get(_BOT_DATA_MCP_CLIENT)
    if mcp_client is not None:
        try:
            await mcp_client.disconnect()
        except Exception:
            log.exception("Error disconnecting MCP client")

    close_checkpointer = application.bot_data.get(_BOT_DATA_CHECKPOINTER_CLOSE)
    if close_checkpointer is not None:
        try:
            await close_checkpointer()
        except Exception:
            log.exception("Error closing checkpointer")

    try:
        flush_tracing()
    except Exception:
        log.exception("Error flushing Langfuse")


def start_bot(settings: Settings) -> None:
    """Build the Telegram application and start polling. Blocking."""
    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.bot_data[_BOT_DATA_SETTINGS] = settings
    app.add_handler(CommandHandler("start", _start_command))

    log.info("Starting Telegram polling…")
    app.run_polling(drop_pending_updates=True)
