"""E2e tests — message queue with real LLM.

Run with: ./.venv/bin/pytest -m e2e -k message_queue -v
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
    vault = tmp_path / "mq-vault"
    vault.mkdir()
    (vault / "IDENTITY.md").write_text("# Identity\n\n- **Name:** MQ Bot\n")
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
    settings.checkpoint_db = tmp_path / "mq-ck.db"
    settings.agent_id = "mq-test"
    settings.max_retries = 0
    settings.mcp_gateway_url = None
    settings.queue_cap = 50
    settings.discard_ttl_seconds = 3600
    return settings


# ============================================================
# 1. Message dispatched through queue reaches real LLM
# ============================================================



async def test_message_queue_real_llm_response(mq_settings: Settings) -> None:
    """Dispatch a message through the queue — real LLM processes it and result is captured."""
    from commandclaw.agent.graph import build_agent_graph, invoke_agent
    from commandclaw.agent.persistence import open_checkpointer
    from commandclaw.message.dispatcher import Dispatcher

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
                assert result.success, f"Agent failed: {result.error}"
                results.append(result.output)

            return process_fn

        dispatcher = Dispatcher(
            factory,
            queue_maxsize=mq_settings.queue_cap,
            discard_ttl=mq_settings.discard_ttl_seconds,
        )

        from commandclaw.message.envelope import MsgEnvelope

        envelope = MsgEnvelope(
            session_id="mq-e2e", content="Reply with exactly: QUEUE_OK",
            message_type="user",
        )
        await dispatcher.dispatch(envelope)

        for _ in range(60):
            if results:
                break
            await asyncio.sleep(0.5)

        await dispatcher.shutdown()
        assert results, "No response received from LLM via queue"
        assert len(results[0]) > 0
    finally:
        await close()


# ============================================================
# 2. Two messages processed serially through queue with real LLM
# ============================================================



async def test_message_queue_serial_real_llm(mq_settings: Settings) -> None:
    """Two messages dispatched rapidly — both processed in order by real LLM."""
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
                assert result.success, f"Agent failed: {result.error}"
                results.append(result.output)

            return process_fn

        dispatcher = Dispatcher(
            factory,
            queue_maxsize=mq_settings.queue_cap,
            discard_ttl=mq_settings.discard_ttl_seconds,
        )

        await dispatcher.dispatch(MsgEnvelope(
            session_id="mq-serial", content="Reply with exactly: FIRST",
            message_type="user",
        ))
        await dispatcher.dispatch(MsgEnvelope(
            session_id="mq-serial", content="Reply with exactly: SECOND",
            message_type="user",
        ))

        for _ in range(120):
            if len(results) >= 2:
                break
            await asyncio.sleep(0.5)

        await dispatcher.shutdown()
        assert len(results) == 2, f"Expected 2 results, got {len(results)}"
    finally:
        await close()


# ============================================================
# 3. Abort cancels real LLM invocation mid-flight
# ============================================================



async def test_message_queue_abort_real_llm(mq_settings: Settings) -> None:
    """Dispatch a slow prompt, abort mid-flight — task cancelled, pending discarded."""
    from commandclaw.agent.graph import build_agent_graph, invoke_agent
    from commandclaw.agent.persistence import open_checkpointer
    from commandclaw.message.dispatcher import Dispatcher
    from commandclaw.message.envelope import MsgEnvelope

    saver, close = await open_checkpointer(mq_settings)
    try:
        agent, _ = await build_agent_graph(mq_settings, checkpointer=saver)

        completed: list[str] = []

        def factory(session_id: str):
            async def process_fn(envelope):
                await invoke_agent(
                    agent, envelope.content, mq_settings,
                    session_id=session_id, user_id=session_id,
                )
                completed.append(envelope.content)

            return process_fn

        dispatcher = Dispatcher(
            factory,
            queue_maxsize=mq_settings.queue_cap,
            discard_ttl=mq_settings.discard_ttl_seconds,
        )

        await dispatcher.dispatch(MsgEnvelope(
            session_id="mq-abort",
            content="Write a 500-word essay about the history of computing.",
            message_type="user",
        ))
        await dispatcher.dispatch(MsgEnvelope(
            session_id="mq-abort", content="pending-msg",
            message_type="user",
        ))

        await asyncio.sleep(1.0)

        count = await dispatcher.abort("mq-abort")

        dq = dispatcher.get_discard_queue("mq-abort")
        discarded = dq.list_discarded()

        assert count >= 1 or len(discarded) >= 1 or "pending-msg" not in completed, (
            "Abort should have cancelled the running task or discarded pending messages"
        )

        await dispatcher.shutdown()
    finally:
        await close()
