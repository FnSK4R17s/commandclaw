from __future__ import annotations

import time

from commandclaw.message.envelope import MsgEnvelope


class DiscardQueue:
    """Holds discarded envelopes with time-to-live expiry."""

    def __init__(self, ttl_seconds: float = 3600) -> None:
        self.ttl_seconds = ttl_seconds
        self._store: list[tuple[MsgEnvelope, float]] = []

    def add(self, envelope: MsgEnvelope) -> None:
        expiry = time.time() + self.ttl_seconds
        self._store.append((envelope, expiry))

    def _live_entries(self) -> list[tuple[MsgEnvelope, float]]:
        now = time.time()
        return [(env, exp) for env, exp in self._store if exp > now]

    def list_discarded(self) -> list[MsgEnvelope]:
        return [env for env, _ in self._live_entries()]

    def recover(self, index: int) -> MsgEnvelope:
        live = self._live_entries()
        if index < 0 or index >= len(live):
            raise IndexError(f"index {index} out of range for {len(live)} non-expired entries")
        target_env, target_exp = live[index]
        self._store.remove((target_env, target_exp))
        return target_env

    def recover_all(self) -> list[MsgEnvelope]:
        result = self.list_discarded()
        self._store.clear()
        return result

    def expire(self) -> None:
        self._store = self._live_entries()

    def __len__(self) -> int:
        return len(self._live_entries())
