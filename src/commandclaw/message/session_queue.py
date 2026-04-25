from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from commandclaw.message.envelope import MsgEnvelope


class SessionQueue:
    def __init__(
        self,
        process_fn: Callable[[MsgEnvelope], Awaitable[None]],
        *,
        maxsize: int = 200,
        discard_queue=None,
    ) -> None:
        self._process_fn = process_fn
        self._queue: asyncio.Queue[MsgEnvelope] = asyncio.Queue(maxsize=maxsize)
        self._discard_queue = discard_queue
        self._drain_task: asyncio.Task | None = None

    async def enqueue(self, envelope: MsgEnvelope) -> None:
        self._queue.put_nowait(envelope)

    async def _drain(self) -> None:
        while True:
            envelope = await self._queue.get()
            try:
                await self._process_fn(envelope)
            except asyncio.CancelledError:
                self._queue.task_done()
                raise
            self._queue.task_done()

    async def start(self) -> None:
        self._drain_task = asyncio.create_task(self._drain())

    async def stop(self) -> None:
        if self._drain_task is not None:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
            self._drain_task = None

    async def abort(self) -> int:
        if self._drain_task is not None:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
            self._drain_task = None

        count = 0
        while not self._queue.empty():
            try:
                envelope = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if self._discard_queue is not None:
                self._discard_queue.add(envelope)
                count += 1
            self._queue.task_done()

        await self.start()
        return count
