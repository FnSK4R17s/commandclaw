"""Tests for commandclaw.message.discard.DiscardQueue."""

from __future__ import annotations

import time

import pytest

from commandclaw.message.discard import DiscardQueue
from commandclaw.message.envelope import MsgEnvelope


def _make_envelope(content: str, message_type: str = "user") -> MsgEnvelope:
    return MsgEnvelope(session_id="sess-1", content=content, message_type=message_type)


class TestDiscardQueueListOrder:
    def test_add_two_envelopes_list_discarded_returns_both_in_insertion_order(self) -> None:
        queue = DiscardQueue(ttl_seconds=3600)
        env_a = _make_envelope("first")
        env_b = _make_envelope("second")
        queue.add(env_a)
        queue.add(env_b)
        result = queue.list_discarded()
        assert result == [env_a, env_b]


class TestDiscardQueueRecoverByIndex:
    def test_recover_returns_correct_envelope_and_removes_it(self) -> None:
        queue = DiscardQueue(ttl_seconds=3600)
        env_a = _make_envelope("alpha")
        env_b = _make_envelope("beta")
        queue.add(env_a)
        queue.add(env_b)
        recovered = queue.recover(0)
        assert recovered == env_a
        assert queue.list_discarded() == [env_b]

    def test_recover_invalid_index_raises_index_error(self) -> None:
        queue = DiscardQueue(ttl_seconds=3600)
        queue.add(_make_envelope("only"))
        with pytest.raises(IndexError):
            queue.recover(5)


class TestDiscardQueueRecoverAll:
    def test_recover_all_returns_all_envelopes_and_empties_queue(self) -> None:
        queue = DiscardQueue(ttl_seconds=3600)
        env_a = _make_envelope("one")
        env_b = _make_envelope("two")
        queue.add(env_a)
        queue.add(env_b)
        result = queue.recover_all()
        assert result == [env_a, env_b]
        assert queue.list_discarded() == []


class TestDiscardQueueExpiry:
    def test_expired_entries_are_excluded_from_list_discarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        frozen_time = 1_000_000.0
        monkeypatch.setattr(time, "time", lambda: frozen_time)

        queue = DiscardQueue(ttl_seconds=1.0)
        queue.add(_make_envelope("will-expire"))

        # Advance time past ttl
        monkeypatch.setattr(time, "time", lambda: frozen_time + 2.0)
        queue.expire()

        assert queue.list_discarded() == []


class TestDiscardQueueLen:
    def test_len_reflects_count_after_add_recover_and_expiry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        frozen_time = 2_000_000.0
        monkeypatch.setattr(time, "time", lambda: frozen_time)

        queue = DiscardQueue(ttl_seconds=10.0)
        assert len(queue) == 0

        queue.add(_make_envelope("msg-1"))
        queue.add(_make_envelope("msg-2"))
        queue.add(_make_envelope("msg-3"))
        assert len(queue) == 3

        queue.recover(0)
        assert len(queue) == 2

        # Advance time to expire the remaining two
        monkeypatch.setattr(time, "time", lambda: frozen_time + 20.0)
        queue.expire()
        assert len(queue) == 0
