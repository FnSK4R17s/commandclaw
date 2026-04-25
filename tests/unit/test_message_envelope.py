"""Tests for commandclaw.message.envelope.MsgEnvelope — frozen dataclass."""

from __future__ import annotations

import time

import pytest

from commandclaw.message.envelope import MsgEnvelope


class TestMsgEnvelopeConstruction:
    def test_all_fields_set_correctly(self) -> None:
        env = MsgEnvelope(
            session_id="sess-1",
            content="hello",
            message_type="user",
            timestamp=1_000_000.0,
        )
        assert env.session_id == "sess-1"
        assert env.content == "hello"
        assert env.message_type == "user"
        assert env.timestamp == 1_000_000.0


class TestMsgEnvelopeFrozen:
    def test_assigning_attribute_raises(self) -> None:
        env = MsgEnvelope(session_id="s", content="c", message_type="user", timestamp=1.0)
        with pytest.raises((TypeError, AttributeError)):
            env.content = "mutated"  # type: ignore[misc]


class TestMsgEnvelopeDefaultTimestamp:
    def test_timestamp_defaults_to_current_time(self) -> None:
        before = time.time()
        env = MsgEnvelope(session_id="s", content="c", message_type="user")
        after = time.time()
        assert before <= env.timestamp <= after


class TestMsgEnvelopeMessageTypeValidation:
    def test_invalid_message_type_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            MsgEnvelope(session_id="s", content="c", message_type="invalid", timestamp=1.0)

    def test_valid_message_types_are_accepted(self) -> None:
        for mtype in ("user", "control", "server"):
            env = MsgEnvelope(session_id="s", content="c", message_type=mtype, timestamp=1.0)
            assert env.message_type == mtype
