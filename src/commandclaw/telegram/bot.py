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

from commandclaw.agent.graph import build_agent_graph, invoke_agent
from commandclaw.agent.persistence import open_checkpointer
from commandclaw.config import Settings
from commandclaw.message.dispatcher import Dispatcher
from commandclaw.telegram.handlers import create_message_handler
from commandclaw.telegram.sender import send_error_alert, send_message

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

    factory = create_process_fn_factory(agent, settings, application.bot)
    dispatcher = Dispatcher(
        factory,
        queue_maxsize=settings.queue_cap,
        discard_ttl=settings.discard_ttl_seconds,
    )
    application.bot_data["dispatcher"] = dispatcher

    handler = create_message_handler(settings)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler, block=False))
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


async def _stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stop — abort the current session's queue."""
    if update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    session_id = str(chat_id)
    dispatcher = context.application.bot_data.get("dispatcher")
    if dispatcher is None:
        return
    count = await dispatcher.abort(session_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Agent stopped. {count} messages moved to discard queue.",
    )


async def _discarded_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /discarded — list discarded messages."""
    if update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    session_id = str(chat_id)
    dispatcher = context.application.bot_data.get("dispatcher")
    if dispatcher is None:
        return
    dq = dispatcher.get_discard_queue(session_id)
    items = dq.list_discarded()
    if not items:
        await context.bot.send_message(chat_id=chat_id, text="No discarded messages.")
        return
    lines = []
    for i, env in enumerate(items, start=1):
        lines.append(f"{i}. {env.content}")
    await context.bot.send_message(
        chat_id=chat_id,
        text="Discarded messages:\n" + "\n".join(lines) + "\n\n/recover <n> or /recover all",
    )


async def _recover_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /recover <n> or /recover all — re-enqueue discarded messages."""
    if update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    session_id = str(chat_id)
    dispatcher = context.application.bot_data.get("dispatcher")
    if dispatcher is None:
        return
    dq = dispatcher.get_discard_queue(session_id)
    args = context.args or []
    if not args:
        await context.bot.send_message(chat_id=chat_id, text="Usage: /recover <n> or /recover all")
        return
    if args[0].lower() == "all":
        recovered = dq.recover_all()
        for env in recovered:
            await dispatcher.dispatch(env)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Recovered {len(recovered)} messages.",
        )
    else:
        try:
            user_index = int(args[0])  # 1-indexed from user
        except ValueError:
            await context.bot.send_message(
                chat_id=chat_id, text="Usage: /recover <n> or /recover all"
            )
            return
        env = dq.recover(user_index - 1)  # 0-indexed internally
        await dispatcher.dispatch(env)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Recovered message: {env.content}",
        )


def create_process_fn_factory(agent, settings, bot):
    """Build a factory that produces per-session process functions for the Dispatcher."""

    def factory(session_id):
        async def process_fn(envelope):
            result = await invoke_agent(
                agent,
                envelope.content,
                settings,
                session_id=session_id,
                user_id=session_id,
            )
            if result.success:
                await send_message(
                    bot,
                    int(session_id),
                    result.output,
                    chunk_size=settings.telegram_chunk_size,
                )
            else:
                await send_error_alert(
                    bot,
                    int(session_id),
                    result.error or "Unknown error",
                )

        return process_fn

    return factory


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
    app.add_handler(CommandHandler("stop", _stop_command), group=-1)
    app.add_handler(CommandHandler("discarded", _discarded_command))
    app.add_handler(CommandHandler("recover", _recover_command))

    log.info("Starting Telegram polling…")
    app.run_polling(drop_pending_updates=True)
