"""Tests for commandclaw.vault.agent_config and commandclaw.vault.identity."""

from __future__ import annotations

from pathlib import Path

from commandclaw.vault.agent_config import AgentConfig, load_agent_config
from commandclaw.vault.identity import (
    Identity,
    VaultIdentity,
    _parse_identity_md,
    load_identity,
)

_SAMPLE_IDENTITY_MD = """\
# Identity

- **Name:** CommandClaw
- **Creature:** crab
- **Vibe:** helpful and curious
- **Emoji:** 🦀
- **Avatar:** claw.png

## Origin
Born in the deep sea of version control, CommandClaw emerged
to guard vaults and automate tasks.
"""


class TestLoadAgentConfig:
    def test_existing_agents_md(self, tmp_path: Path) -> None:
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text("You are a helpful agent.\n")
        cfg = load_agent_config(tmp_path)
        assert isinstance(cfg, AgentConfig)
        assert cfg.raw_text == "You are a helpful agent.\n"

    def test_missing_agents_md(self, tmp_path: Path) -> None:
        cfg = load_agent_config(tmp_path)
        assert cfg.raw_text == ""


class TestParseIdentityMd:
    def test_parses_all_fields(self) -> None:
        ident = _parse_identity_md(_SAMPLE_IDENTITY_MD)
        assert ident.name == "CommandClaw"
        assert ident.creature == "crab"
        assert ident.vibe == "helpful and curious"
        assert ident.emoji == "\U0001f980"
        assert ident.avatar == "claw.png"
        assert "Born in the deep sea" in ident.origin

    def test_empty_text(self) -> None:
        ident = _parse_identity_md("")
        assert ident == Identity()

    def test_partial_fields(self) -> None:
        text = "- **Name:** Clawbot\n"
        ident = _parse_identity_md(text)
        assert ident.name == "Clawbot"
        assert ident.creature == ""


class TestLoadIdentity:
    def test_all_files_present(self, tmp_path: Path) -> None:
        (tmp_path / "IDENTITY.md").write_text(_SAMPLE_IDENTITY_MD)
        (tmp_path / "SOUL.md").write_text("soul text")
        (tmp_path / "USER.md").write_text("user text")
        (tmp_path / "TOOLS.md").write_text("tools text")
        (tmp_path / "HEARTBEAT.md").write_text("heartbeat text")

        vi = load_identity(tmp_path)
        assert isinstance(vi, VaultIdentity)
        assert vi.identity.name == "CommandClaw"
        assert vi.soul == "soul text"
        assert vi.user == "user text"
        assert vi.tools == "tools text"
        assert vi.heartbeat == "heartbeat text"

    def test_missing_files(self, tmp_path: Path) -> None:
        vi = load_identity(tmp_path)
        assert vi.identity == Identity()
        assert vi.soul == ""
        assert vi.user == ""
