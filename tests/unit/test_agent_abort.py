"""Tests for abort_event support in invoke_agent.

These tests verify that invoke_agent accepts an optional abort_event parameter
(asyncio.Event) that can cancel invocation before or during agent.ainvoke().
The abort_event parameter does not yet exist — these tests are RED by design.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from commandclaw.agent.context import AgentResult
from commandclaw.agent.graph import invoke_agent
from commandclaw.config import Settings
from commandclaw.vault.git_ops import VaultRepo


# ============================================================
# Helpers
# ============================================================


def _make_settings(tmp_path) -> Settings:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "IDENTITY.md").write_text("# Identity\n\n- **Name:** Test Agent\n")
    (vault / "AGENTS.md").write_text("# Workspace Rules\n\nBe helpful.\n")
    (vault / "USER.md").write_text("# User\n\nDeveloper.\n")
    (vault / "SOUL.md").write_text("# Soul\n\nCurious.\n")
    VaultRepo(vault).ensure_repo()
    return Settings(
        vault_path=vault,
        agent_id="test",
        openai_api_key="sk-test",
        openai_model="gpt-test",
        openai_base_url=None,
        telegram_bot_token="test-token",
        checkpoint_db=tmp_path / "ck.db",
        max_retries=0,
        retry_base_delay=0.0,
        mcp_gateway_url=None,
        mcp_agent_key=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )


def _make_mock_agent(response_content: str = "hello") -> AsyncMock:
    """Build a minimal fake agent whose ainvoke returns a valid messages dict."""
    agent = AsyncMock()
    agent.ainvoke = AsyncMock(
        return_value={"messages": [AIMessage(content=response_content)]}
    )
    return agent


# ============================================================
# Test 1 — backward compat: works without abort_event
# ============================================================


async def test_invoke_agent_without_abort_event_returns_success(tmp_path):
    """invoke_agent with abort_event=None (default) returns AgentResult(success=True)."""
    settings = _make_settings(tmp_path)
    agent = _make_mock_agent("pong")

    result = await invoke_agent(agent, "ping", settings, abort_event=None)

    assert isinstance(result, AgentResult)
    assert result.success is True
    assert result.output == "pong"


# ============================================================
# Test 2 — abort before first attempt raises CancelledError
# ============================================================


async def test_invoke_agent_with_preset_abort_event_raises_cancelled_error(tmp_path):
    """invoke_agent raises CancelledError immediately when abort_event is already set."""
    settings = _make_settings(tmp_path)
    agent = _make_mock_agent()

    event = asyncio.Event()
    event.set()  # set before call

    with pytest.raises(asyncio.CancelledError):
        await invoke_agent(agent, "ping", settings, abort_event=event)

    # agent.ainvoke must never have been called
    agent.ainvoke.assert_not_called()


# ============================================================
# Test 3 — abort mid-flight cancels the ainvoke task
# ============================================================


async def test_invoke_agent_abort_event_set_during_ainvoke_cancels_task(tmp_path):
    """Setting abort_event while agent.ainvoke is running causes CancelledError."""
    settings = _make_settings(tmp_path)

    # ainvoke sleeps 10 s — will be cancelled before it completes
    async def _slow_ainvoke(*_args, **_kwargs):
        await asyncio.sleep(10)
        return {"messages": [AIMessage(content="too late")]}

    agent = AsyncMock()
    agent.ainvoke = AsyncMock(side_effect=_slow_ainvoke)

    event = asyncio.Event()

    async def _trigger_abort():
        await asyncio.sleep(0.02)  # let ainvoke start
        event.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.gather(
            invoke_agent(agent, "ping", settings, abort_event=event),
            _trigger_abort(),
            return_exceptions=False,
        )
