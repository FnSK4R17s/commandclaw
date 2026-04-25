"""Telegram message handlers — dispatch to the agent via the message queue."""

from __future__ import annotations

import logging
from collections.abc import Callable

from telegram import Update
from telegram.ext import ContextTypes

from commandclaw.config import Settings
from commandclaw.message.envelope import MsgEnvelope
from commandclaw.telegram.sender import send_error_alert

log = logging.getLogger(__name__)


def create_message_handler(
    settings: Settings,
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], object]:
    """Return a PTB handler that forwards text messages to the dispatcher."""

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

        dispatcher = context.application.bot_data.get("dispatcher")
        if dispatcher is None:
            log.error("Dispatcher not initialised — dropping message from %s", chat_id)
            await send_error_alert(context.bot, chat_id, "Agent not ready, retry shortly.")
            return

        envelope = MsgEnvelope(
            session_id=str(chat_id),
            content=text,
            message_type="user",
        )

        try:
            await dispatcher.dispatch(envelope)
        except Exception:
            log.exception("Unhandled error dispatching message for chat %s", chat_id)
            await send_error_alert(
                context.bot,
                chat_id,
                "An unexpected error occurred. Please try again.",
            )

    return handler
