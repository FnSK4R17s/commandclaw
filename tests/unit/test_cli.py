"""Tests for commandclaw.cli — arg parsing and settings resolution."""

from __future__ import annotations

from pathlib import Path

from commandclaw.cli import parse_mode, resolve_settings
from commandclaw.config import Settings

# ============================================================
# parse_mode
# ============================================================


class TestParseMode:
    def test_default_is_telegram(self) -> None:
        assert parse_mode([]) == "telegram"

    def test_chat_mode(self) -> None:
        assert parse_mode(["chat"]) == "chat"

    def test_bootstrap_mode(self) -> None:
        assert parse_mode(["bootstrap"]) == "bootstrap"

    def test_telegram_mode_explicit(self) -> None:
        assert parse_mode(["telegram"]) == "telegram"

    def test_unknown_mode_passes_through(self) -> None:
        assert parse_mode(["bogus"]) == "bogus"

    def test_extra_args_ignored(self) -> None:
        assert parse_mode(["chat", "--verbose"]) == "chat"


# ============================================================
# resolve_settings
# ============================================================


class TestResolveSettings:
    def test_vault_path_already_set_is_unchanged(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        settings = Settings(
            vault_path=vault,
            openai_api_key="sk-test",
            telegram_bot_token="tok",
        )
        result = resolve_settings(settings)
        assert result.vault_path == vault

    def test_agent_id_preserved_when_vault_set(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        settings = Settings(
            vault_path=vault,
            agent_id="my-agent",
            openai_api_key="sk-test",
            telegram_bot_token="tok",
        )
        result = resolve_settings(settings)
        assert result.agent_id == "my-agent"
