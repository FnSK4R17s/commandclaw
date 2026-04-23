"""Pure-logic tests for ``commandclaw.vault.workspace.generate_agent_id``.

The format and word-list contract is the user-visible API — it shows up in
docker container names, log lines, and the chat header. Lock both.
"""

from __future__ import annotations

import re

from commandclaw.vault.workspace import _ADJECTIVES, _ANIMALS, generate_agent_id

_AGENT_ID = re.compile(r"^[a-z]+-[a-z]+-\d{4}$")


def test_generate_agent_id_matches_expected_format() -> None:
    agent_id = generate_agent_id()
    assert _AGENT_ID.match(agent_id), agent_id


def test_generate_agent_id_uses_known_words() -> None:
    adj, animal, _ = generate_agent_id().split("-")
    assert adj in _ADJECTIVES
    assert animal in _ANIMALS or (adj == "holy" and animal == "cow")


def test_generate_agent_id_suffix_is_zero_padded() -> None:
    suffix = generate_agent_id().split("-")[-1]
    assert len(suffix) == 4
    assert suffix.isdigit()


def test_generate_agent_id_is_unique_across_calls() -> None:
    # 50 calls in a tight loop — the time-based hash gives different ns each time.
    ids = {generate_agent_id() for _ in range(50)}
    assert len(ids) > 1
