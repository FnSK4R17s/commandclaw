"""Telegram message handlers — dispatch to the agent."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from telegram import Update
from telegram.ext import ContextTypes

from commandclaw.agent.graph import invoke_agent
from commandclaw.config import Settings
from commandclaw.telegram.sender import send_error_alert, send_message

log = logging.getLogger(__name__)

_chat_locks: dict[int, asyncio.Lock] = {}


def _lock_for(chat_id: int) -> asyncio.Lock:
    if chat_id not in _chat_locks:
        _chat_locks[chat_id] = asyncio.Lock()
    return _chat_locks[chat_id]


def create_message_handler(
    settings: Settings,
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], object]:
    """Return a PTB handler that forwards text messages to the agent."""

    async def handler(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if update.effective_chat is None or update.message is None:
            return

        chat_id: int = update.effective_chat.id
        text: str | None = update.message.text
        if not text:
            return

        if (
            settings.telegram_allowed_chat_ids
            and chat_id not in settings.telegram_allowed_chat_ids
        ):
            log.warning("Rejected message from unauthorised chat %s", chat_id)
            return

        agent = context.application.bot_data.get("agent")
        if agent is None:
            log.error("Agent not initialised — dropping message from %s", chat_id)
            await send_error_alert(context.bot, chat_id, "Agent not ready, retry shortly.")
            return

        async with _lock_for(chat_id):
            try:
                result = await invoke_agent(
                    agent,
                    text,
                    settings,
                    session_id=str(chat_id),
                    user_id=str(chat_id),
                )
            except Exception:
                log.exception("Unhandled error invoking agent for chat %s", chat_id)
                await send_error_alert(
                    context.bot,
                    chat_id,
                    "An unexpected error occurred. Please try again.",
                )
                return

            if result.success:
                await send_message(
                    context.bot,
                    chat_id,
                    result.output,
                    chunk_size=settings.telegram_chunk_size,
                )
            else:
                await send_error_alert(
                    context.bot,
                    chat_id,
                    result.error or "Unknown error",
                )

    return handler
