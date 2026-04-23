"""Pure-logic tests for telegram chunk splitter + bot interaction with a fake Bot."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from telegram.error import TelegramError

from commandclaw.telegram.sender import _split_text, send_error_alert, send_message

# ============================================================
# _split_text — pure
# ============================================================


def test_split_text_short_returns_single_chunk() -> None:
    assert _split_text("hello", 100) == ["hello"]


def test_split_text_prefers_newline_boundary() -> None:
    text = "line1\nline2\nline3"
    chunks = _split_text(text, 12)
    assert chunks == ["line1\nline2", "line3"]


def test_split_text_hard_cuts_when_no_newline_in_window() -> None:
    text = "abcdefghij" * 5
    chunks = _split_text(text, 10)
    assert all(len(c) <= 10 for c in chunks)
    assert "".join(chunks) == text


def test_split_text_handles_exact_boundary() -> None:
    assert _split_text("abcde", 5) == ["abcde"]


def test_split_text_strips_leading_newlines_after_split() -> None:
    text = "abc\n\ndef"
    chunks = _split_text(text, 3)
    assert chunks[0] == "abc"
    assert chunks[1].lstrip("\n") == chunks[1]


# ============================================================
# send_message — markdown fallback
# ============================================================


async def test_send_message_chunks_long_text() -> None:
    bot = AsyncMock()
    text = "line\n" * 1000
    await send_message(bot, chat_id=42, text=text, chunk_size=100)
    assert bot.send_message.await_count > 1
    for call in bot.send_message.await_args_list:
        assert call.kwargs["chat_id"] == 42
        assert len(call.kwargs["text"]) <= 100


async def test_send_message_falls_back_to_plain_on_markdown_error() -> None:
    bot = AsyncMock()
    bot.send_message = AsyncMock(side_effect=[
        TelegramError("bad markdown"),
        None,  # plain-text retry succeeds
    ])
    await send_message(bot, chat_id=1, text="hello *world", chunk_size=100)
    assert bot.send_message.await_count == 2
    first, second = bot.send_message.await_args_list
    assert first.kwargs["parse_mode"] == "Markdown"
    assert "parse_mode" not in second.kwargs


async def test_send_message_swallows_repeated_failure() -> None:
    bot = AsyncMock()
    bot.send_message = AsyncMock(side_effect=TelegramError("down"))
    # Must not raise even when both attempts fail.
    await send_message(bot, chat_id=1, text="x", chunk_size=100)


async def test_send_message_skips_empty() -> None:
    bot = AsyncMock()
    await send_message(bot, chat_id=1, text="", chunk_size=100)
    bot.send_message.assert_not_called()


async def test_send_error_alert_prefixes_warning() -> None:
    bot = AsyncMock()
    await send_error_alert(bot, chat_id=7, error="boom")
    bot.send_message.assert_awaited_once()
    text = bot.send_message.await_args.kwargs["text"]
    assert "boom" in text
    assert "Agent error" in text


@pytest.mark.parametrize("chunk_size", [10, 50, 4000])
def test_split_text_never_exceeds_size(chunk_size: int) -> None:
    text = "x\n" * 5000
    for chunk in _split_text(text, chunk_size):
        assert len(chunk) <= chunk_size
