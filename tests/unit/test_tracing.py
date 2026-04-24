"""Tests for commandclaw.tracing.langfuse_tracing.

Each test creates a fresh ``TracingManager`` — no global state, no monkeypatch.
Langfuse SDK is not called (keys are empty), so these run in milliseconds.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from commandclaw.config import Settings
from commandclaw.tracing.langfuse_tracing import (
    TracingManager,
    create_langfuse_handler,
    flush_tracing,
    reset_default_manager,
)

# ============================================================
# Helpers
# ============================================================


def _settings(
    *,
    public_key: str | None = None,
    secret_key: str | None = None,
    host: str = "https://cloud.langfuse.com",
    agent_id: str = "test-agent",
    tmp_path: Path | None = None,
) -> Settings:
    return Settings(
        vault_path=tmp_path or Path("/tmp/test-vault"),
        agent_id=agent_id,
        openai_api_key="sk-test",
        telegram_bot_token="tok",
        langfuse_public_key=public_key,
        langfuse_secret_key=secret_key,
        langfuse_host=host,
        mcp_gateway_url=None,
    )


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_default_manager()


# ============================================================
# TracingManager — no keys
# ============================================================


class TestTracingManagerDisabled:
    def test_no_keys_returns_disabled(self) -> None:
        mgr = TracingManager(_settings())
        assert mgr.create_handler() is None
        assert mgr.is_enabled is False

    def test_empty_public_key(self) -> None:
        mgr = TracingManager(_settings(public_key="", secret_key="sk-lf-secret"))
        assert mgr.create_handler() is None

    def test_empty_secret_key(self) -> None:
        mgr = TracingManager(_settings(public_key="pk-lf-public", secret_key=""))
        assert mgr.create_handler() is None

    def test_none_keys(self) -> None:
        mgr = TracingManager(_settings(public_key=None, secret_key=None))
        assert mgr.create_handler() is None

    def test_flush_safe_when_disabled(self) -> None:
        mgr = TracingManager(_settings())
        mgr.flush()  # should not raise

    def test_ensure_only_runs_once(self) -> None:
        mgr = TracingManager(_settings())
        mgr._ensure()
        assert mgr._initialized is True
        mgr._ensure()
        assert mgr._initialized is True


# ============================================================
# TracingManager — with keys (mocked Langfuse)
# ============================================================


class TestTracingManagerEnabled:
    def test_creates_client_with_keys(self) -> None:
        s = _settings(public_key="pk-lf-test", secret_key="sk-lf-test")
        mgr = TracingManager(s)

        mock_langfuse = MagicMock()
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_langfuse)}):
            result = mgr._ensure()

        assert result is True
        assert mgr.is_enabled is True
        mock_langfuse.assert_called_once_with(
            public_key="pk-lf-test",
            secret_key="sk-lf-test",
            host="https://cloud.langfuse.com",
        )

    def test_create_handler_with_mocked_langfuse(self) -> None:
        s = _settings(public_key="pk-lf-test", secret_key="sk-lf-test")
        mgr = TracingManager(s)

        mock_handler_cls = MagicMock()
        mock_langfuse_mod = MagicMock()
        mock_langfuse_mod.langchain.CallbackHandler = mock_handler_cls

        with patch.dict("sys.modules", {
            "langfuse": MagicMock(Langfuse=MagicMock()),
            "langfuse.langchain": mock_langfuse_mod.langchain,
        }):
            mgr._ensure()
            handler = mgr.create_handler(session_id="s1", user_id="u1")

        assert handler is not None

    def test_flush_calls_client(self) -> None:
        s = _settings(public_key="pk-lf-test", secret_key="sk-lf-test")
        mgr = TracingManager(s)
        mgr._client = MagicMock()
        mgr._initialized = True

        mgr.flush()
        mgr._client.flush.assert_called_once()

    def test_flush_handles_error(self) -> None:
        s = _settings(public_key="pk-lf-test", secret_key="sk-lf-test")
        mgr = TracingManager(s)
        mgr._client = MagicMock()
        mgr._client.flush.side_effect = RuntimeError("network error")
        mgr._initialized = True

        mgr.flush()  # should not raise

    def test_import_error_disables_tracing(self) -> None:
        s = _settings(public_key="pk-lf-test", secret_key="sk-lf-test")
        mgr = TracingManager(s)

        with patch.dict("sys.modules", {"langfuse": None}):
            result = mgr._ensure()

        assert result is False
        assert mgr.is_enabled is False


# ============================================================
# Isolation between instances
# ============================================================


class TestTracingIsolation:
    def test_separate_instances_dont_share_state(self) -> None:
        s1 = _settings(public_key=None, secret_key=None)
        s2 = _settings(public_key=None, secret_key=None)
        mgr1 = TracingManager(s1)
        mgr2 = TracingManager(s2)

        mgr1._ensure()
        assert mgr1._initialized is True
        assert mgr2._initialized is False

    def test_different_settings_per_instance(self) -> None:
        mgr1 = TracingManager(_settings(host="https://host1.example.com"))
        mgr2 = TracingManager(_settings(host="https://host2.example.com"))
        assert mgr1._settings.langfuse_host != mgr2._settings.langfuse_host


# ============================================================
# Module-level convenience functions
# ============================================================


class TestModuleLevelFunctions:
    def test_create_handler_returns_none_without_keys(self) -> None:
        s = _settings()
        assert create_langfuse_handler(s) is None

    def test_flush_tracing_safe_when_uninitialized(self) -> None:
        flush_tracing()  # should not raise

    def test_create_handler_creates_singleton(self) -> None:
        s = _settings()
        create_langfuse_handler(s)
        create_langfuse_handler(s)  # should reuse
