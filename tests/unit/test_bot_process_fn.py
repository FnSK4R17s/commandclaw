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
    async def test_process_fn_calls_invoke_agent_and_sends_result(self) -> None:
        """process_fn invokes the agent with the envelope content and sends the result to the user."""
        mock_agent = MagicMock()
        mock_bot = AsyncMock()
        settings = _make_settings(chunk_size=4000)

        success_result = AgentResult(output="hello from agent", success=True)

        envelope = MsgEnvelope(session_id="7", content="user message", message_type="user")

        with (
            patch("commandclaw.telegram.bot.invoke_agent", new=AsyncMock(return_value=success_result)) as mock_invoke,
            patch("commandclaw.telegram.bot.send_message", new=AsyncMock()) as mock_send,
            patch("commandclaw.telegram.bot.send_error_alert", new=AsyncMock()) as mock_send_error,
        ):
            factory = create_process_fn_factory(mock_agent, settings, mock_bot)
            process_fn = factory("7")
            await process_fn(envelope)

            mock_invoke.assert_called_once_with(
                mock_agent,
                "user message",
                settings,
                session_id="7",
                user_id="7",
            )
            mock_send.assert_called_once_with(
                mock_bot,
                7,
                "hello from agent",
                chunk_size=4000,
            )
            mock_send_error.assert_not_called()

    async def test_process_fn_sends_error_on_failure(self) -> None:
        """process_fn calls send_error_alert when invoke_agent returns success=False."""
        mock_agent = MagicMock()
        mock_bot = AsyncMock()
        settings = _make_settings()

        failure_result = AgentResult(output="", success=False, error="boom")

        envelope = MsgEnvelope(session_id="42", content="fail me", message_type="user")

        with (
            patch("commandclaw.telegram.bot.invoke_agent", new=AsyncMock(return_value=failure_result)) as mock_invoke,
            patch("commandclaw.telegram.bot.send_message", new=AsyncMock()) as mock_send,
            patch("commandclaw.telegram.bot.send_error_alert", new=AsyncMock()) as mock_send_error,
        ):
            factory = create_process_fn_factory(mock_agent, settings, mock_bot)
            process_fn = factory("42")
            await process_fn(envelope)

            mock_invoke.assert_called_once_with(
                mock_agent,
                "fail me",
                settings,
                session_id="42",
                user_id="42",
            )
            mock_send.assert_not_called()
            mock_send_error.assert_called_once_with(mock_bot, 42, "boom")
