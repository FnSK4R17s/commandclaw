"""Integration tests for the message queue — real Dispatcher + SessionQueue + DiscardQueue.

Each test maps to an acceptance criterion from plan/message-queue/02-requirements.md.
The agent is a fake async callable; everything else is real.
"""

from __future__ import annotations

import asyncio

import pytest

from commandclaw.message.discard import DiscardQueue
from commandclaw.message.dispatcher import Dispatcher
from commandclaw.message.envelope import MsgEnvelope

pytestmark = pytest.mark.integration


def _envelope(content: str, session_id: str = "sess-1", message_type: str = "user") -> MsgEnvelope:
    return MsgEnvelope(session_id=session_id, content=content, message_type=message_type)


# ---------------------------------------------------------------------------
# 1. /stop cancels running invocation, pending moved to discard
# ---------------------------------------------------------------------------


async def test_stop_cancels_running_and_discards_pending() -> None:
    processed: list[str] = []

    def factory(session_id: str):
        async def process_fn(envelope: MsgEnvelope) -> None:
            if envelope.content == "slow":
                await asyncio.sleep(10)
            processed.append(envelope.content)

        return process_fn

    dispatcher = Dispatcher(factory, queue_maxsize=10, discard_ttl=3600)

    await dispatcher.dispatch(_envelope("slow"))
    await dispatcher.dispatch(_envelope("pending-1"))
    await dispatcher.dispatch(_envelope("pending-2"))

    await asyncio.sleep(0.02)

    count = await dispatcher.abort("sess-1")

    assert count == 2, f"Expected 2 discarded, got {count}"
    assert "slow" not in processed, "Slow task should have been cancelled"

    dq = dispatcher.get_discard_queue("sess-1")
    discarded = dq.list_discarded()
    contents = [e.content for e in discarded]
    assert "pending-1" in contents
    assert "pending-2" in contents

    await dispatcher.shutdown()


# ---------------------------------------------------------------------------
# 2. Serial FIFO processing — 3 messages processed in order, one at a time
# ---------------------------------------------------------------------------


async def test_serial_fifo_processing() -> None:
    processed: list[str] = []
    active = 0
    concurrency_violation = False

    def factory(session_id: str):
        async def process_fn(envelope: MsgEnvelope) -> None:
            nonlocal active, concurrency_violation
            active += 1
            if active > 1:
                concurrency_violation = True
            await asyncio.sleep(0.01)
            processed.append(envelope.content)
            active -= 1

        return process_fn

    dispatcher = Dispatcher(factory, queue_maxsize=10)

    await dispatcher.dispatch(_envelope("first"))
    await dispatcher.dispatch(_envelope("second"))
    await dispatcher.dispatch(_envelope("third"))

    await asyncio.sleep(0.15)
    await dispatcher.shutdown()

    assert processed == ["first", "second", "third"], f"FIFO violated: {processed}"
    assert not concurrency_violation, "Messages were processed concurrently"


# ---------------------------------------------------------------------------
# 3. Discard queue recoverable — /stop moves, /recover re-enqueues
# ---------------------------------------------------------------------------


async def test_discard_recoverable_via_dispatcher() -> None:
    processed: list[str] = []

    def factory(session_id: str):
        async def process_fn(envelope: MsgEnvelope) -> None:
            if envelope.content == "block":
                await asyncio.sleep(10)
            processed.append(envelope.content)

        return process_fn

    dispatcher = Dispatcher(factory, queue_maxsize=10, discard_ttl=3600)

    await dispatcher.dispatch(_envelope("block"))
    await dispatcher.dispatch(_envelope("recoverable"))
    await asyncio.sleep(0.02)

    await dispatcher.abort("sess-1")

    dq = dispatcher.get_discard_queue("sess-1")
    assert len(dq) == 1

    recovered = dq.recover(0)
    assert recovered.content == "recoverable"

    await dispatcher.dispatch(recovered)
    await asyncio.sleep(0.05)
    await dispatcher.shutdown()

    assert "recoverable" in processed


# ---------------------------------------------------------------------------
# 4. Queue cap rejection — 201st message rejected
# ---------------------------------------------------------------------------


async def test_queue_cap_rejects_overflow() -> None:
    gate = asyncio.Event()

    def factory(session_id: str):
        async def process_fn(envelope: MsgEnvelope) -> None:
            await gate.wait()

        return process_fn

    dispatcher = Dispatcher(factory, queue_maxsize=3)

    # fill-1 dispatched and picked up by drain loop (blocks on gate)
    await dispatcher.dispatch(_envelope("fill-1"))
    await asyncio.sleep(0.02)

    # fill-2, fill-3, fill-4 fill the queue to maxsize=3
    await dispatcher.dispatch(_envelope("fill-2"))
    await dispatcher.dispatch(_envelope("fill-3"))
    await dispatcher.dispatch(_envelope("fill-4"))

    with pytest.raises(asyncio.QueueFull):
        await dispatcher.dispatch(_envelope("overflow"))

    gate.set()
    await dispatcher.shutdown()


# ---------------------------------------------------------------------------
# 5. Server events process in order alongside user messages
# ---------------------------------------------------------------------------


async def test_server_events_process_in_order_with_user_messages() -> None:
    processed: list[tuple[str, str]] = []

    def factory(session_id: str):
        async def process_fn(envelope: MsgEnvelope) -> None:
            processed.append((envelope.message_type, envelope.content))

        return process_fn

    dispatcher = Dispatcher(factory, queue_maxsize=10)

    await dispatcher.dispatch(_envelope("user-msg-1", message_type="user"))
    await dispatcher.dispatch(_envelope("cron-daily", message_type="server"))
    await dispatcher.dispatch(_envelope("user-msg-2", message_type="user"))

    await asyncio.sleep(0.1)
    await dispatcher.shutdown()

    assert processed == [
        ("user", "user-msg-1"),
        ("server", "cron-daily"),
        ("user", "user-msg-2"),
    ], f"Order violated: {processed}"
