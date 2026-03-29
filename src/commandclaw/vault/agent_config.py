"""Load AGENTS.md — the workspace rules that go verbatim into the system prompt."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Raw content of AGENTS.md for injection into the system prompt."""

    raw_text: str


def load_agent_config(vault_path: Path) -> AgentConfig:
    """Read AGENTS.md from the vault root. Returns empty text if missing."""
    agents_file = vault_path / "AGENTS.md"
    if not agents_file.exists():
        logger.warning("AGENTS.md not found in %s", vault_path)
        return AgentConfig(raw_text="")
    return AgentConfig(raw_text=agents_file.read_text(encoding="utf-8"))
