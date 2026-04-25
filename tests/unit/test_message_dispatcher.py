"""Tests for commandclaw.message.dispatcher.Dispatcher."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from commandclaw.message.discard import DiscardQueue
from commandclaw.message.dispatcher import Dispatcher
from commandclaw.message.envelope import MsgEnvelope


def _make_envelope(content: str, session_id: str = "sess-1") -> MsgEnvelope:
    return MsgEnvelope(session_id=session_id, content=content, message_type="user")


class TestDispatchCreatesSessionOnFirstMessage:
    async def test_dispatch_first_envelope_calls_factory_and_processes_message(self) -> None:
        received: list[MsgEnvelope] = []
        factory_calls: list[str] = []

        def factory(session_id: str) -> Callable[[MsgEnvelope], Awaitable[Any]]:
            factory_calls.append(session_id)

            async def process(envelope: MsgEnvelope) -> None:
                received.append(envelope)

            return process

        dispatcher = Dispatcher(factory)
        env = _make_envelope("hello", session_id="sess-1")
        await dispatcher.dispatch(env)

        await asyncio.sleep(0.05)
        await dispatcher.shutdown()

        assert "sess-1" in factory_calls, "factory was not called with the session_id"
        assert env in received, "envelope was not processed by the session's process_fn"


class TestDispatchRoutesToCorrectSession:
    async def test_two_sessions_each_receive_only_their_own_messages(self) -> None:
        received: dict[str, list[MsgEnvelope]] = {}

        def factory(session_id: str) -> Callable[[MsgEnvelope], Awaitable[Any]]:
            received[session_id] = []

            async def process(envelope: MsgEnvelope) -> None:
                received[session_id].append(envelope)

            return process

        dispatcher = Dispatcher(factory)
        env_a = _make_envelope("msg-for-sess-1", session_id="sess-1")
        env_b = _make_envelope("msg-for-sess-2", session_id="sess-2")

        await dispatcher.dispatch(env_a)
        await dispatcher.dispatch(env_b)

        await asyncio.sleep(0.05)
        await dispatcher.shutdown()

        assert received.get("sess-1") == [env_a], "sess-1 received unexpected messages"
        assert received.get("sess-2") == [env_b], "sess-2 received unexpected messages"


class TestAbortForwardsToSessionQueue:
    async def test_abort_session_returns_discard_count_of_pending_messages(self) -> None:
        def factory(session_id: str) -> Callable[[MsgEnvelope], Awaitable[Any]]:
            async def slow_process(envelope: MsgEnvelope) -> None:
                await asyncio.sleep(10)  # blocks so pending messages accumulate

            return slow_process

        dispatcher = Dispatcher(factory)
        env_running = _make_envelope("running", session_id="sess-1")
        env_pending_1 = _make_envelope("pending-1", session_id="sess-1")
        env_pending_2 = _make_envelope("pending-2", session_id="sess-1")

        await dispatcher.dispatch(env_running)
        await dispatcher.dispatch(env_pending_1)
        await dispatcher.dispatch(env_pending_2)

        await asyncio.sleep(0.02)  # drain picks up env_running and blocks

        discard_count = await dispatcher.abort("sess-1")

        assert discard_count == 2, (
            f"abort() returned {discard_count}, expected 2 pending messages discarded"
        )


class TestAbortUnknownSessionRaisesKeyError:
    async def test_abort_unknown_session_id_raises_key_error(self) -> None:
        def factory(session_id: str) -> Callable[[MsgEnvelope], Awaitable[Any]]:
            async def process(envelope: MsgEnvelope) -> None:
                pass

            return process

        dispatcher = Dispatcher(factory)

        with pytest.raises(KeyError):
            await dispatcher.abort("nonexistent")


class TestGetDiscardQueueReturnsSessionDiscardQueue:
    async def test_get_discard_queue_after_dispatch_returns_discard_queue_instance(self) -> None:
        def factory(session_id: str) -> Callable[[MsgEnvelope], Awaitable[Any]]:
            async def process(envelope: MsgEnvelope) -> None:
                pass

            return process

        dispatcher = Dispatcher(factory)
        env = _make_envelope("hello", session_id="sess-1")
        await dispatcher.dispatch(env)

        await asyncio.sleep(0.02)
        await dispatcher.shutdown()

        dq = dispatcher.get_discard_queue("sess-1")
        assert isinstance(dq, DiscardQueue), (
            f"get_discard_queue returned {type(dq).__name__}, expected DiscardQueue"
        )
