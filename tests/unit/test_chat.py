"""Tests for commandclaw.chat — bootstrap message and chat loop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from commandclaw.chat import build_bootstrap_message, chat_loop
from commandclaw.config import Settings

# ============================================================
# build_bootstrap_message
# ============================================================


class TestBuildBootstrapMessage:
    def test_includes_intro(self) -> None:
        msg = build_bootstrap_message("I am a developer")
        assert "I am a developer" in msg
        assert "BOOTSTRAP.md" in msg

    def test_empty_intro_placeholder(self) -> None:
        msg = build_bootstrap_message("")
        assert "(no introduction provided)" in msg

    def test_contains_instructions(self) -> None:
        msg = build_bootstrap_message("hello")
        assert "IDENTITY.md" in msg
        assert "USER.md" in msg
        assert "daily note" in msg


# ============================================================
# chat_loop — non-bootstrap (normal chat)
# ============================================================


class TestChatLoopNormalMode:
    @pytest.fixture
    def chat_settings(self, tmp_vault: Path, tmp_path: Path) -> Settings:
        return Settings(
            vault_path=tmp_vault,
            agent_id="test-agent",
            openai_api_key="sk-test",
            openai_model="gpt-test",
            telegram_bot_token="tok",
            checkpoint_db=tmp_path / "ck.db",
            max_retries=0,
            mcp_gateway_url=None,
            langfuse_public_key=None,
            langfuse_secret_key=None,
        )

    async def test_exit_command_ends_loop(self, chat_settings: Settings) -> None:
        agent = AsyncMock()
        close_ck = AsyncMock()
        inputs = iter(["exit"])

        printed: list[str] = []
        await chat_loop(
            chat_settings,
            agent,
            mcp_client=None,
            close_checkpointer=close_ck,
            input_fn=lambda _: next(inputs),
            print_fn=lambda *a: printed.append(" ".join(str(x) for x in a)),
        )

        close_ck.assert_awaited_once()
        agent.ainvoke.assert_not_called()

    async def test_quit_command_ends_loop(self, chat_settings: Settings) -> None:
        agent = AsyncMock()
        close_ck = AsyncMock()
        inputs = iter(["quit"])

        await chat_loop(
            chat_settings,
            agent,
            mcp_client=None,
            close_checkpointer=close_ck,
            input_fn=lambda _: next(inputs),
            print_fn=lambda *a: None,
        )

        close_ck.assert_awaited_once()

    async def test_empty_input_skipped(self, chat_settings: Settings) -> None:
        from commandclaw.agent.graph import AgentResult

        agent = AsyncMock()
        close_ck = AsyncMock()
        inputs = iter(["", "  ", "hello", "exit"])

        mock_result = AgentResult(output="hi", success=True)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "commandclaw.agent.graph.invoke_agent",
                AsyncMock(return_value=mock_result),
            )
            await chat_loop(
                chat_settings,
                agent,
                mcp_client=None,
                close_checkpointer=close_ck,
                input_fn=lambda _: next(inputs),
                print_fn=lambda *a: None,
            )

    async def test_eof_ends_loop(self, chat_settings: Settings) -> None:
        agent = AsyncMock()
        close_ck = AsyncMock()

        def eof_input(_: str) -> str:
            raise EOFError

        await chat_loop(
            chat_settings,
            agent,
            mcp_client=None,
            close_checkpointer=close_ck,
            input_fn=eof_input,
            print_fn=lambda *a: None,
        )

        close_ck.assert_awaited_once()

    async def test_mcp_client_disconnected_on_exit(self, chat_settings: Settings) -> None:
        agent = AsyncMock()
        close_ck = AsyncMock()
        mcp = AsyncMock()
        inputs = iter(["exit"])

        await chat_loop(
            chat_settings,
            agent,
            mcp_client=mcp,
            close_checkpointer=close_ck,
            input_fn=lambda _: next(inputs),
            print_fn=lambda *a: None,
        )

        mcp.disconnect.assert_awaited_once()

    async def test_successful_response_printed(self, chat_settings: Settings) -> None:
        from commandclaw.agent.graph import AgentResult

        agent = AsyncMock()
        close_ck = AsyncMock()
        inputs = iter(["hello", "exit"])
        printed: list[str] = []

        mock_result = AgentResult(output="agent says hi", success=True)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "commandclaw.agent.graph.invoke_agent",
                AsyncMock(return_value=mock_result),
            )
            await chat_loop(
                chat_settings,
                agent,
                mcp_client=None,
                close_checkpointer=close_ck,
                input_fn=lambda _: next(inputs),
                print_fn=lambda *a: printed.append(" ".join(str(x) for x in a)),
            )

        assert any("agent says hi" in line for line in printed)

    async def test_failed_response_prints_error(self, chat_settings: Settings) -> None:
        from commandclaw.agent.graph import AgentResult

        agent = AsyncMock()
        close_ck = AsyncMock()
        inputs = iter(["hello", "exit"])
        printed: list[str] = []

        mock_result = AgentResult(output="", success=False, error="boom")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "commandclaw.agent.graph.invoke_agent",
                AsyncMock(return_value=mock_result),
            )
            await chat_loop(
                chat_settings,
                agent,
                mcp_client=None,
                close_checkpointer=close_ck,
                input_fn=lambda _: next(inputs),
                print_fn=lambda *a: printed.append(" ".join(str(x) for x in a)),
            )

        assert any("boom" in line for line in printed)

    async def test_goodbye_always_printed(self, chat_settings: Settings) -> None:
        agent = AsyncMock()
        close_ck = AsyncMock()
        inputs = iter(["exit"])
        printed: list[str] = []

        await chat_loop(
            chat_settings,
            agent,
            mcp_client=None,
            close_checkpointer=close_ck,
            input_fn=lambda _: next(inputs),
            print_fn=lambda *a: printed.append(" ".join(str(x) for x in a)),
        )

        assert any("Goodbye" in line for line in printed)
