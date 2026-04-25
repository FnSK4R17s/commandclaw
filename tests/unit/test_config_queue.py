"""Tests for queue-related fields on commandclaw.config.Settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from commandclaw.config import Settings


def _base_settings(tmp_path: Path, **overrides) -> Settings:
    """Minimal valid Settings suitable for unit tests."""
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    return Settings(
        vault_path=vault,
        agent_id="test",
        openai_api_key="sk-test",
        telegram_bot_token="tok",
        checkpoint_db=tmp_path / "ck.db",
        mcp_gateway_url=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
        **overrides,
    )


class TestQueueCapDefault:
    def test_default_settings_has_queue_cap_200(self, tmp_path: Path) -> None:
        settings = _base_settings(tmp_path)
        assert settings.queue_cap == 200


class TestDiscardTtlSecondsDefault:
    def test_default_settings_has_discard_ttl_seconds_3600(self, tmp_path: Path) -> None:
        settings = _base_settings(tmp_path)
        assert settings.discard_ttl_seconds == 3600


class TestQueueCapOverride:
    def test_settings_with_queue_cap_50_stores_50(self, tmp_path: Path) -> None:
        settings = _base_settings(tmp_path, queue_cap=50)
        assert settings.queue_cap == 50


class TestDiscardTtlSecondsOverride:
    def test_settings_with_discard_ttl_seconds_7200_stores_7200(self, tmp_path: Path) -> None:
        settings = _base_settings(tmp_path, discard_ttl_seconds=7200)
        assert settings.discard_ttl_seconds == 7200
