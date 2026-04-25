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


class StreamingSender:
    """Accumulates tokens and progressively edits a Telegram message.

    Telegram rate-limits ``editMessageText`` to ~1 call/sec per chat.
    Tokens are buffered locally and flushed on a 1-second cadence.
    Call ``finalize()`` after the stream ends to send the final text.
    """

    def __init__(self, bot: Bot, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._parts: list[str] = []
        self._msg_id: int | None = None
        self._last_edit: float = 0.0

    async def on_token(self, token: str) -> None:
        import time

        self._parts.append(token)
        now = time.monotonic()
        text = "".join(self._parts)

        if self._msg_id is None:
            try:
                sent = await self._bot.send_message(
                    chat_id=self._chat_id, text=text,
                )
                self._msg_id = sent.message_id
                self._last_edit = now
            except TelegramError:
                log.debug("Failed to send initial streaming message", exc_info=True)
        elif now - self._last_edit >= 1.0:
            try:
                await self._bot.edit_message_text(
                    chat_id=self._chat_id,
                    message_id=self._msg_id,
                    text=text,
                )
                self._last_edit = now
            except TelegramError:
                log.debug("Failed to edit streaming message", exc_info=True)

    async def finalize(self) -> None:
        text = "".join(self._parts)
        if not text:
            return
        if self._msg_id is not None:
            try:
                await self._bot.edit_message_text(
                    chat_id=self._chat_id,
                    message_id=self._msg_id,
                    text=text,
                )
            except TelegramError:
                log.debug("Failed to finalize streaming message", exc_info=True)
        else:
            await send_message(self._bot, self._chat_id, text)


async def send_error_alert(bot: Bot, chat_id: int, error: str) -> None:
    """Send a failure alert to the user."""
    text = f"⚠️ Agent error:\n\n{error}"
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except TelegramError:
        log.exception("Failed to send error alert to chat %s", chat_id)
