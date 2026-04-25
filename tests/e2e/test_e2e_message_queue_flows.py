"""E2e tests — full message queue flows with real LLM.

Covers multi-step flows: stop→discard→recover→re-process, server events,
and TUI→Dispatcher→LLM pipeline.

Run with: ./.venv/bin/pytest -m e2e -k message_queue_flows -v
Keys loaded from .env via conftest.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from commandclaw.config import Settings

pytestmark = pytest.mark.e2e


def _load_settings() -> Settings:
    return Settings()


@pytest.fixture
def e2e_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "mqf-vault"
    vault.mkdir()
    (vault / "IDENTITY.md").write_text("# Identity\n\n- **Name:** Flow Bot\n")
    (vault / "AGENTS.md").write_text("# Rules\n\nBe concise. One sentence max.\n")
    (vault / "USER.md").write_text("# User\n\nTester.\n")
    (vault / "SOUL.md").write_text("# Soul\n\nDirect.\n")
    from commandclaw.vault.git_ops import VaultRepo

    VaultRepo(vault).ensure_repo()
    return vault


@pytest.fixture
def mq_settings(e2e_vault: Path, tmp_path: Path) -> Settings:
    settings = _load_settings()
    settings.vault_path = e2e_vault
    settings.checkpoint_db = tmp_path / "mqf-ck.db"
    settings.agent_id = "mqf-test"
    settings.max_retries = 0
    settings.mcp_gateway_url = None
    settings.queue_cap = 50
    settings.discard_ttl_seconds = 3600
    return settings


# ============================================================
# 1. Full /stop → discard → /recover → re-process with real LLM
# ============================================================


async def test_stop_discard_recover_reprocess(mq_settings: Settings) -> None:
    """Send a slow prompt + pending message, abort, recover pending, re-process with real LLM."""
    from commandclaw.agent.graph import build_agent_graph, invoke_agent
    from commandclaw.agent.persistence import open_checkpointer
    from commandclaw.message.dispatcher import Dispatcher
    from commandclaw.message.envelope import MsgEnvelope

    saver, close = await open_checkpointer(mq_settings)
    try:
        agent, _ = await build_agent_graph(mq_settings, checkpointer=saver)

        results: list[str] = []

        def factory(session_id: str):
            async def process_fn(envelope):
                result = await invoke_agent(
                    agent, envelope.content, mq_settings,
                    session_id=session_id, user_id=session_id,
                )
                if result.success:
                    results.append(result.output)

            return process_fn

        dispatcher = Dispatcher(
            factory, queue_maxsize=50, discard_ttl=mq_settings.discard_ttl_seconds,
        )

        # Send a slow prompt that will be running when we abort
        await dispatcher.dispatch(MsgEnvelope(
            session_id="flow-1",
            content="Write a detailed 300-word essay about ancient Rome.",
            message_type="user",
        ))
        # Pending message that will be discarded
        await dispatcher.dispatch(MsgEnvelope(
            session_id="flow-1",
            content="Reply with exactly: RECOVERED",
            message_type="user",
        ))

        await asyncio.sleep(1.0)
        count = await dispatcher.abort("flow-1")

        assert count >= 1, f"Expected at least 1 discarded, got {count}"

        # Recover the pending message
        dq = dispatcher.get_discard_queue("flow-1")
        recovered = dq.recover_all()
        assert len(recovered) >= 1

        # Re-dispatch recovered messages
        for env in recovered:
            await dispatcher.dispatch(env)

        # Wait for re-processing
        for _ in range(60):
            if results:
                break
            await asyncio.sleep(0.5)

        await dispatcher.shutdown()
        assert results, "Recovered message was not processed by the LLM"
    finally:
        await close()


# ============================================================
# 2. Server event processed by real LLM through queue
# ============================================================


async def test_server_event_processed_by_real_llm(mq_settings: Settings) -> None:
    """A server-type envelope enters the queue and is processed by the real LLM."""
    from commandclaw.agent.graph import build_agent_graph, invoke_agent
    from commandclaw.agent.persistence import open_checkpointer
    from commandclaw.message.dispatcher import Dispatcher
    from commandclaw.message.envelope import MsgEnvelope

    saver, close = await open_checkpointer(mq_settings)
    try:
        agent, _ = await build_agent_graph(mq_settings, checkpointer=saver)

        results: list[str] = []

        def factory(session_id: str):
            async def process_fn(envelope):
                result = await invoke_agent(
                    agent, envelope.content, mq_settings,
                    session_id=session_id, user_id=session_id,
                )
                if result.success:
                    results.append(result.output)

            return process_fn

        dispatcher = Dispatcher(
            factory, queue_maxsize=50, discard_ttl=mq_settings.discard_ttl_seconds,
        )

        await dispatcher.dispatch(MsgEnvelope(
            session_id="server-e2e",
            content="Reply with exactly: CRON_OK",
            message_type="server",
        ))

        for _ in range(60):
            if results:
                break
            await asyncio.sleep(0.5)

        await dispatcher.shutdown()
        assert results, "Server event was not processed"
        assert len(results[0]) > 0
    finally:
        await close()


# ============================================================
# 3. process_fn_factory → real LLM → send_message pipeline
# ============================================================


async def test_process_fn_factory_real_llm(mq_settings: Settings) -> None:
    """create_process_fn_factory wires invoke_agent to send_message with real LLM."""
    from unittest.mock import AsyncMock

    from commandclaw.agent.graph import build_agent_graph
    from commandclaw.agent.persistence import open_checkpointer
    from commandclaw.message.dispatcher import Dispatcher
    from commandclaw.message.envelope import MsgEnvelope
    from commandclaw.telegram.bot import create_process_fn_factory

    saver, close = await open_checkpointer(mq_settings)
    try:
        agent, _ = await build_agent_graph(mq_settings, checkpointer=saver)

        mock_bot = AsyncMock()

        factory = create_process_fn_factory(agent, mq_settings, mock_bot)
        dispatcher = Dispatcher(
            factory, queue_maxsize=50, discard_ttl=mq_settings.discard_ttl_seconds,
        )

        await dispatcher.dispatch(MsgEnvelope(
            session_id="77",
            content="Reply with exactly: FACTORY_OK",
            message_type="user",
        ))

        for _ in range(60):
            if mock_bot.send_message.called:
                break
            await asyncio.sleep(0.5)

        await dispatcher.shutdown()
        assert mock_bot.send_message.called, "send_message was never called"
    finally:
        await close()


# ============================================================
# 4. Two sessions processed concurrently by real LLM
# ============================================================


async def test_two_sessions_concurrent_real_llm(mq_settings: Settings) -> None:
    """Two sessions dispatch simultaneously — both get LLM responses."""
    from commandclaw.agent.graph import build_agent_graph, invoke_agent
    from commandclaw.agent.persistence import open_checkpointer
    from commandclaw.message.dispatcher import Dispatcher
    from commandclaw.message.envelope import MsgEnvelope

    saver, close = await open_checkpointer(mq_settings)
    try:
        agent, _ = await build_agent_graph(mq_settings, checkpointer=saver)

        results: dict[str, list[str]] = {"s1": [], "s2": []}

        def factory(session_id: str):
            async def process_fn(envelope):
                result = await invoke_agent(
                    agent, envelope.content, mq_settings,
                    session_id=session_id, user_id=session_id,
                )
                if result.success:
                    results[session_id].append(result.output)

            return process_fn

        dispatcher = Dispatcher(
            factory, queue_maxsize=50, discard_ttl=mq_settings.discard_ttl_seconds,
        )

        await dispatcher.dispatch(MsgEnvelope(
            session_id="s1", content="Reply with exactly: S1_OK", message_type="user",
        ))
        await dispatcher.dispatch(MsgEnvelope(
            session_id="s2", content="Reply with exactly: S2_OK", message_type="user",
        ))

        for _ in range(90):
            if results["s1"] and results["s2"]:
                break
            await asyncio.sleep(0.5)

        await dispatcher.shutdown()
        assert results["s1"], "Session s1 got no response"
        assert results["s2"], "Session s2 got no response"
    finally:
        await close()
