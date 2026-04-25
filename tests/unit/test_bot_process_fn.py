"""Unit tests for create_process_fn_factory — builds per-session process functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from commandclaw.agent.context import AgentResult
from commandclaw.message.envelope import MsgEnvelope
from commandclaw.telegram.bot import create_process_fn_factory


def _make_settings(chunk_size: int = 4000) -> MagicMock:
    settings = MagicMock()
    settings.telegram_chunk_size = chunk_size
    return settings


class TestProcessFnFactory:
    async def test_process_fn_streams_and_finalizes(self) -> None:
        """process_fn streams tokens via StreamingSender and finalizes on success."""
        mock_agent = MagicMock()
        mock_bot = AsyncMock()
        settings = _make_settings(chunk_size=4000)

        success_result = AgentResult(output="hello from agent", success=True)

        envelope = MsgEnvelope(session_id="7", content="user message", message_type="user")

        async def fake_stream(agent, msg, s, *, session_id, user_id, on_token=None):
            if on_token is not None:
                await on_token("hello ")
                await on_token("from agent")
            return success_result

        with (
            patch("commandclaw.telegram.bot.stream_agent", side_effect=fake_stream) as mock_stream,
            patch("commandclaw.telegram.bot.send_error_alert", new=AsyncMock()) as mock_err,
        ):
            factory = create_process_fn_factory(mock_agent, settings, mock_bot)
            process_fn = factory("7")
            await process_fn(envelope)

            mock_stream.assert_called_once()
            call_kwargs = mock_stream.call_args
            assert call_kwargs[0][1] == "user message"
            assert call_kwargs[1]["session_id"] == "7"
            mock_err.assert_not_called()
            assert mock_bot.send_message.called

    async def test_process_fn_sends_error_on_failure(self) -> None:
        """process_fn calls send_error_alert when stream_agent returns success=False."""
        mock_agent = MagicMock()
        mock_bot = AsyncMock()
        settings = _make_settings()

        failure_result = AgentResult(output="", success=False, error="boom")

        envelope = MsgEnvelope(session_id="42", content="fail me", message_type="user")

        async def fake_stream(agent, msg, s, *, session_id, user_id, on_token=None):
            return failure_result

        with (
            patch("commandclaw.telegram.bot.stream_agent", side_effect=fake_stream),
            patch("commandclaw.telegram.bot.send_error_alert", new=AsyncMock()) as mock_err,
        ):
            factory = create_process_fn_factory(mock_agent, settings, mock_bot)
            process_fn = factory("42")
            await process_fn(envelope)

            mock_err.assert_called_once_with(mock_bot, 42, "boom")
