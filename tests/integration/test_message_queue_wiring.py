"""Integration tests — wiring between message queue components and adapters.

Real Dispatcher + SessionQueue + DiscardQueue + handler/bot/TUI adapters.
Agent is a controllable fake (async callable). No LLM.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from commandclaw.agent.context import AgentResult
from commandclaw.message.discard import DiscardQueue
from commandclaw.message.dispatcher import Dispatcher
from commandclaw.message.envelope import MsgEnvelope

pytestmark = pytest.mark.integration


def _envelope(content: str, session_id: str = "sess-1", message_type: str = "user") -> MsgEnvelope:
    return MsgEnvelope(session_id=session_id, content=content, message_type=message_type)


# ---------------------------------------------------------------------------
# 1. Telegram handler → Dispatcher pipeline
# ---------------------------------------------------------------------------


async def test_telegram_handler_dispatches_through_real_queue() -> None:
    """Handler constructs envelope, Dispatcher routes to SessionQueue, process_fn fires."""
    from commandclaw.config import Settings
    from commandclaw.telegram.handlers import create_message_handler

    processed: list[MsgEnvelope] = []

    def factory(session_id: str):
        async def process_fn(envelope: MsgEnvelope) -> None:
            processed.append(envelope)

        return process_fn

    dispatcher = Dispatcher(factory, queue_maxsize=10)

    settings = MagicMock(spec=Settings)
    settings.telegram_allowed_chat_ids = []

    handler = create_message_handler(settings)

    update = MagicMock()
    update.effective_chat = SimpleNamespace(id=777)
    update.message = SimpleNamespace(text="integration test")

    ctx = MagicMock()
    ctx.application.bot_data = {"dispatcher": dispatcher}
    ctx.bot = AsyncMock()

    await handler(update, ctx)
    await asyncio.sleep(0.05)
    await dispatcher.shutdown()

    assert len(processed) == 1
    assert processed[0].session_id == "777"
    assert processed[0].content == "integration test"
    assert processed[0].message_type == "user"


# ---------------------------------------------------------------------------
# 2. Bot /stop through real Dispatcher
# ---------------------------------------------------------------------------


async def test_bot_stop_command_aborts_real_dispatcher() -> None:
    """/stop command aborts a real session queue, pending messages land in discard."""
    from commandclaw.telegram.bot import _stop_command

    gate = asyncio.Event()
    processed: list[str] = []

    def factory(session_id: str):
        async def process_fn(envelope: MsgEnvelope) -> None:
            if envelope.content == "slow":
                await gate.wait()
            processed.append(envelope.content)

        return process_fn

    dispatcher = Dispatcher(factory, queue_maxsize=10, discard_ttl=3600)

    await dispatcher.dispatch(_envelope("slow", session_id="42"))
    await dispatcher.dispatch(_envelope("pending", session_id="42"))
    await asyncio.sleep(0.02)

    update = MagicMock()
    update.effective_chat = SimpleNamespace(id=42)
    ctx = MagicMock()
    ctx.application.bot_data = {"dispatcher": dispatcher}
    ctx.bot = AsyncMock()

    await _stop_command(update, ctx)

    ctx.bot.send_message.assert_called_once()
    text = ctx.bot.send_message.call_args.kwargs["text"]
    assert "stopped" in text.lower()
    assert "1" in text

    dq = dispatcher.get_discard_queue("42")
    assert len(dq) == 1
    assert dq.list_discarded()[0].content == "pending"

    gate.set()
    await dispatcher.shutdown()


# ---------------------------------------------------------------------------
# 3. Bot /discarded + /recover through real Dispatcher
# ---------------------------------------------------------------------------


async def test_bot_discarded_and_recover_with_real_queue() -> None:
    """/discarded lists real discard entries, /recover re-enqueues them."""
    from commandclaw.telegram.bot import _discarded_command, _recover_command

    gate = asyncio.Event()
    processed: list[str] = []

    def factory(session_id: str):
        async def process_fn(envelope: MsgEnvelope) -> None:
            if envelope.content == "block":
                await gate.wait()
            processed.append(envelope.content)

        return process_fn

    dispatcher = Dispatcher(factory, queue_maxsize=10, discard_ttl=3600)

    await dispatcher.dispatch(_envelope("block", session_id="99"))
    await dispatcher.dispatch(_envelope("save-me", session_id="99"))
    await asyncio.sleep(0.02)
    await dispatcher.abort("99")

    # /discarded
    update = MagicMock()
    update.effective_chat = SimpleNamespace(id=99)
    ctx = MagicMock()
    ctx.application.bot_data = {"dispatcher": dispatcher}
    ctx.bot = AsyncMock()

    await _discarded_command(update, ctx)
    text = ctx.bot.send_message.call_args.kwargs["text"]
    assert "save-me" in text
    assert "1." in text

    # /recover all
    ctx.args = ["all"]
    ctx.bot.reset_mock()
    await _recover_command(update, ctx)
    await asyncio.sleep(0.05)

    assert "save-me" in processed
    await dispatcher.shutdown()


# ---------------------------------------------------------------------------
# 4. invoke_agent abort_event — real async cancellation
# ---------------------------------------------------------------------------


async def test_invoke_agent_abort_event_cancels_real_task() -> None:
    """abort_event set mid-flight cancels the real asyncio.Task wrapping ainvoke."""
    from commandclaw.agent.graph import invoke_agent

    slow_agent = MagicMock()

    async def _slow_ainvoke(*args, **kwargs):
        await asyncio.sleep(10)

    slow_agent.ainvoke = _slow_ainvoke

    settings = MagicMock()
    settings.vault_path = "/tmp"
    settings.agent_id = "test"
    settings.openai_api_key = None
    settings.max_retries = 0
    settings.retry_base_delay = 0

    event = asyncio.Event()

    async def trigger():
        await asyncio.sleep(0.05)
        event.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.gather(
            invoke_agent(slow_agent, "test", settings, abort_event=event),
            trigger(),
        )


# ---------------------------------------------------------------------------
# 5. process_fn_factory wiring — real Dispatcher, fake agent
# ---------------------------------------------------------------------------


async def test_process_fn_factory_wires_invoke_to_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """process_fn_factory connects invoke_agent result to send_message through real Dispatcher."""
    from commandclaw.telegram.bot import create_process_fn_factory

    mock_result = AgentResult(output="agent says hi", success=True)
    mock_invoke = AsyncMock(return_value=mock_result)
    mock_send = AsyncMock()
    monkeypatch.setattr("commandclaw.telegram.bot.invoke_agent", mock_invoke)
    monkeypatch.setattr("commandclaw.telegram.bot.send_message", mock_send)

    agent = MagicMock()
    settings = MagicMock()
    settings.telegram_chunk_size = 4000
    settings.queue_cap = 10
    settings.discard_ttl_seconds = 60
    bot = AsyncMock()

    factory = create_process_fn_factory(agent, settings, bot)
    dispatcher = Dispatcher(factory, queue_maxsize=10, discard_ttl=60)

    await dispatcher.dispatch(_envelope("hello", session_id="55"))
    await asyncio.sleep(0.05)
    await dispatcher.shutdown()

    mock_invoke.assert_called_once()
    mock_send.assert_called_once_with(bot, 55, "agent says hi", chunk_size=4000)


# ---------------------------------------------------------------------------
# 6. Multiple sessions run concurrently with isolation
# ---------------------------------------------------------------------------


async def test_multiple_sessions_run_concurrently() -> None:
    """Two sessions process their messages concurrently, each in FIFO order."""
    results: dict[str, list[str]] = {"s1": [], "s2": []}

    def factory(session_id: str):
        async def process_fn(envelope: MsgEnvelope) -> None:
            await asyncio.sleep(0.01)
            results[session_id].append(envelope.content)

        return process_fn

    dispatcher = Dispatcher(factory, queue_maxsize=10)

    await dispatcher.dispatch(_envelope("s1-a", session_id="s1"))
    await dispatcher.dispatch(_envelope("s1-b", session_id="s1"))
    await dispatcher.dispatch(_envelope("s2-a", session_id="s2"))
    await dispatcher.dispatch(_envelope("s2-b", session_id="s2"))

    await asyncio.sleep(0.15)
    await dispatcher.shutdown()

    assert results["s1"] == ["s1-a", "s1-b"]
    assert results["s2"] == ["s2-a", "s2-b"]


# ---------------------------------------------------------------------------
# 7. DiscardQueue TTL expiry with real time
# ---------------------------------------------------------------------------


async def test_discard_ttl_expires_entries() -> None:
    """Entries added to DiscardQueue with short TTL expire after the TTL passes."""
    dq = DiscardQueue(ttl_seconds=0.1)

    dq.add(_envelope("ephemeral"))
    assert len(dq) == 1

    await asyncio.sleep(0.15)
    dq.expire()

    assert len(dq) == 0
    assert dq.list_discarded() == []


# ---------------------------------------------------------------------------
# 8. TUI ChatApp → Dispatcher pipeline
# ---------------------------------------------------------------------------


async def test_tui_chatapp_dispatches_through_real_queue() -> None:
    """ChatApp submit flows through real Dispatcher to process_fn."""
    from textual.widgets import Input

    from commandclaw.tui.chat import ChatApp

    processed: list[MsgEnvelope] = []

    def factory(session_id: str):
        async def process_fn(envelope: MsgEnvelope) -> None:
            processed.append(envelope)

        return process_fn

    dispatcher = Dispatcher(factory, queue_maxsize=10)
    app = ChatApp(dispatcher=dispatcher)

    async with app.run_test() as pilot:
        input_widget = app.query_one("#user-input", Input)
        input_widget.value = "tui integration"
        await pilot.press("enter")
        await asyncio.sleep(0.05)

    await dispatcher.shutdown()

    assert len(processed) == 1
    assert processed[0].session_id == "cli"
    assert processed[0].content == "tui integration"


# ---------------------------------------------------------------------------
# 9. TUI ChatApp /stop through real Dispatcher
# ---------------------------------------------------------------------------


async def test_tui_chatapp_stop_aborts_real_queue() -> None:
    """Typing /stop in TUI aborts the session through real Dispatcher."""
    from textual.widgets import Input

    from commandclaw.tui.chat import ChatApp

    gate = asyncio.Event()

    def factory(session_id: str):
        async def process_fn(envelope: MsgEnvelope) -> None:
            await gate.wait()

        return process_fn

    dispatcher = Dispatcher(factory, queue_maxsize=10, discard_ttl=3600)
    app = ChatApp(dispatcher=dispatcher)

    async with app.run_test() as pilot:
        input_widget = app.query_one("#user-input", Input)

        input_widget.value = "block me"
        await pilot.press("enter")
        await asyncio.sleep(0.02)

        input_widget.value = "pending msg"
        await pilot.press("enter")

        input_widget.value = "/stop"
        await pilot.press("enter")
        await asyncio.sleep(0.02)

    stop_msgs = [m for m in app.messages if "stopped" in m.lower()]
    assert stop_msgs, f"Expected 'stopped' message in {app.messages}"

    dq = dispatcher.get_discard_queue("cli")
    discarded = dq.list_discarded()
    assert any(e.content == "pending msg" for e in discarded)

    gate.set()
    await dispatcher.shutdown()
