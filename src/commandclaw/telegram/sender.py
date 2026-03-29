"""Chunked message sender for Telegram."""

from __future__ import annotations

import logging

from telegram import Bot
from telegram.error import TelegramError

log = logging.getLogger(__name__)


def _split_text(text: str, chunk_size: int) -> list[str]:
    """Split *text* into chunks of at most *chunk_size* characters.

    Prefers splitting at the last newline before the limit so messages
    remain readable.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= chunk_size:
            chunks.append(text)
            break

        # Try to split at a newline within the allowed window.
        split_at = text.rfind("\n", 0, chunk_size)
        if split_at <= 0:
            # No convenient newline — hard-cut at the limit.
            split_at = chunk_size

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


async def send_message(
    bot: Bot,
    chat_id: int,
    text: str,
    chunk_size: int = 4000,
) -> None:
    """Send a message, splitting into chunks if it exceeds *chunk_size*."""
    if not text:
        return

    for chunk in _split_text(text, chunk_size):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode="Markdown",
            )
        except TelegramError:
            # Markdown parsing can fail on unescaped characters — retry
            # as plain text so the user still receives the content.
            try:
                await bot.send_message(chat_id=chat_id, text=chunk)
            except TelegramError:
                log.exception(
                    "Failed to send message chunk to chat %s", chat_id
                )


async def send_error_alert(bot: Bot, chat_id: int, error: str) -> None:
    """Send a failure alert to the user."""
    text = f"⚠️ Agent error:\n\n{error}"
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except TelegramError:
        log.exception("Failed to send error alert to chat %s", chat_id)
