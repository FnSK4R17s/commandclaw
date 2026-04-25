from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from commandclaw.message.discard import DiscardQueue
from commandclaw.message.envelope import MsgEnvelope
from commandclaw.message.session_queue import SessionQueue


class Dispatcher:
    def __init__(
        self,
        process_fn_factory: Callable[[str], Callable[[MsgEnvelope], Awaitable[Any]]],
        *,
        queue_maxsize: int = 200,
        discard_ttl: float = 3600,
    ) -> None:
        self._factory = process_fn_factory
        self._queue_maxsize = queue_maxsize
        self._discard_ttl = discard_ttl
        self._sessions: dict[str, tuple[SessionQueue, DiscardQueue]] = {}

    async def dispatch(self, envelope: MsgEnvelope) -> None:
        session_id = envelope.session_id
        if session_id not in self._sessions:
            discard = DiscardQueue(ttl_seconds=self._discard_ttl)
            process_fn = self._factory(session_id)
            sq = SessionQueue(process_fn, maxsize=self._queue_maxsize, discard_queue=discard)
            await sq.start()
            self._sessions[session_id] = (sq, discard)
        sq, _ = self._sessions[session_id]
        await sq.enqueue(envelope)

    async def abort(self, session_id: str) -> int:
        sq, _ = self._sessions[session_id]
        return await sq.abort()

    def get_discard_queue(self, session_id: str) -> DiscardQueue:
        _, dq = self._sessions[session_id]
        return dq

    async def shutdown(self) -> None:
        for sq, _ in self._sessions.values():
            await sq.stop()
