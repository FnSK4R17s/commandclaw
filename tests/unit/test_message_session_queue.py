"""Tests for commandclaw.message.session_queue.SessionQueue."""

from __future__ import annotations

import asyncio

import pytest

from commandclaw.message.envelope import MsgEnvelope
from commandclaw.message.session_queue import SessionQueue


def _make_envelope(content: str, session_id: str = "sess-1") -> MsgEnvelope:
    return MsgEnvelope(session_id=session_id, content=content, message_type="user")


class TestSessionQueueSerialProcessing:
    async def test_enqueue_three_messages_process_fn_receives_all_in_fifo_order(self) -> None:
        received: list[MsgEnvelope] = []

        async def collect(envelope: MsgEnvelope) -> None:
            received.append(envelope)

        env_a = _make_envelope("first")
        env_b = _make_envelope("second")
        env_c = _make_envelope("third")

        queue = SessionQueue(collect)
        await queue.enqueue(env_a)
        await queue.enqueue(env_b)
        await queue.enqueue(env_c)

        await queue.start()
        # Allow the drain loop to process all three envelopes
        await asyncio.sleep(0.05)
        await queue.stop()

        assert received == [env_a, env_b, env_c]


class TestSessionQueueCapRejection:
    async def test_third_enqueue_raises_queue_full_when_maxsize_is_two(self) -> None:
        async def noop(envelope: MsgEnvelope) -> None:
            pass

        queue = SessionQueue(noop, maxsize=2)
        await queue.enqueue(_make_envelope("one"))
        await queue.enqueue(_make_envelope("two"))

        with pytest.raises(asyncio.QueueFull):
            await queue.enqueue(_make_envelope("three"))


class TestSessionQueueSingleMessage:
    async def test_enqueue_one_message_process_fn_called_exactly_once(self) -> None:
        call_count = 0

        async def counter(envelope: MsgEnvelope) -> None:
            nonlocal call_count
            call_count += 1

        env = _make_envelope("only")
        queue = SessionQueue(counter)
        await queue.enqueue(env)

        await queue.start()
        await asyncio.sleep(0.05)
        await queue.stop()

        assert call_count == 1


class TestSessionQueueSequentialDrain:
    async def test_second_message_does_not_start_until_first_finishes(self) -> None:
        active_count = 0
        concurrency_violation = False
        lock = asyncio.Lock()

        async def slow_process(envelope: MsgEnvelope) -> None:
            nonlocal active_count, concurrency_violation
            async with lock:
                active_count += 1
                if active_count > 1:
                    concurrency_violation = True
            await asyncio.sleep(0.02)
            async with lock:
                active_count -= 1

        env_a = _make_envelope("slow-first")
        env_b = _make_envelope("slow-second")

        queue = SessionQueue(slow_process)
        await queue.enqueue(env_a)
        await queue.enqueue(env_b)

        await queue.start()
        # Wait long enough for both to finish (2 * 0.02 s + slack)
        await asyncio.sleep(0.1)
        await queue.stop()

        assert not concurrency_violation, "process_fn was called concurrently — drain loop is not sequential"


class TestSessionQueueAbortCancelsRunningTask:
    async def test_abort_cancels_slow_process_fn_before_it_completes(self) -> None:
        completed = False

        async def slow_process(envelope: MsgEnvelope) -> None:
            nonlocal completed
            await asyncio.sleep(10)  # effectively infinite — abort must interrupt this
            completed = True

        env_a = _make_envelope("slow")
        env_b = _make_envelope("pending")

        queue = SessionQueue(slow_process)
        await queue.enqueue(env_a)
        await queue.enqueue(env_b)

        await queue.start()
        await asyncio.sleep(0.02)  # let drain pick up env_a and block in slow_process

        await queue.abort()

        assert not completed, "process_fn completed — abort() did not cancel the running task"


class TestSessionQueueAbortMovesPendingToDiscardQueue:
    async def test_abort_moves_pending_messages_into_discard_queue(self) -> None:
        from commandclaw.message.discard import DiscardQueue

        async def slow_process(envelope: MsgEnvelope) -> None:
            await asyncio.sleep(10)

        env_a = _make_envelope("running")
        env_b = _make_envelope("pending-1")
        env_c = _make_envelope("pending-2")

        discard = DiscardQueue()
        queue = SessionQueue(slow_process, discard_queue=discard)
        await queue.enqueue(env_a)
        await queue.enqueue(env_b)
        await queue.enqueue(env_c)

        await queue.start()
        await asyncio.sleep(0.02)  # drain picks up env_a; env_b and env_c remain

        await queue.abort()

        discarded = discard.list_discarded()
        assert env_b in discarded, "pending message env_b was not moved to discard_queue"
        assert env_c in discarded, "pending message env_c was not moved to discard_queue"


class TestSessionQueueAbortReturnsDiscardCount:
    async def test_abort_returns_count_of_discarded_messages(self) -> None:
        from commandclaw.message.discard import DiscardQueue

        async def slow_process(envelope: MsgEnvelope) -> None:
            await asyncio.sleep(10)

        env_a = _make_envelope("running")
        env_b = _make_envelope("pending-1")
        env_c = _make_envelope("pending-2")

        discard = DiscardQueue()
        queue = SessionQueue(slow_process, discard_queue=discard)
        await queue.enqueue(env_a)
        await queue.enqueue(env_b)
        await queue.enqueue(env_c)

        await queue.start()
        await asyncio.sleep(0.02)

        count = await queue.abort()

        assert count == 2, f"abort() returned {count}, expected 2 pending messages discarded"


class TestSessionQueueAbortWithoutDiscardQueue:
    async def test_abort_without_discard_queue_cancels_running_task_without_error(self) -> None:
        completed = False

        async def slow_process(envelope: MsgEnvelope) -> None:
            nonlocal completed
            await asyncio.sleep(10)
            completed = True

        env_a = _make_envelope("running")
        env_b = _make_envelope("pending")

        # discard_queue=None (default) — pending messages are lost, no AttributeError
        queue = SessionQueue(slow_process)
        await queue.enqueue(env_a)
        await queue.enqueue(env_b)

        await queue.start()
        await asyncio.sleep(0.02)

        # Must not raise even without a discard_queue
        count = await queue.abort()

        assert not completed, "process_fn completed — abort() did not cancel the running task"
        assert count == 0, f"abort() returned {count}, expected 0 (no discard_queue to count from)"
