"""Shared fixtures for the CommandClaw test suite.

Tiers:

* ``tests/unit/``         pure-Python, no I/O outside ``tmp_path``, no network.
* ``tests/integration/``  real git, real SQLite over ``tmp_path``.
* ``tests/agent/``        compiled graph + ``GenericFakeChatModel``.
* ``tests/e2e/``          real LLM + real Langfuse, opt-in via ``-m e2e``.

The fixtures in this file cover the first three tiers. ``e2e`` tests build their
own settings and skip when API keys are absent.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from commandclaw.config import Settings
from commandclaw.vault.git_ops import VaultRepo

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage


# ============================================================
# Vault
# ============================================================


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    """Minimal initialised vault with the four required markdown files."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "IDENTITY.md").write_text("# Identity\n\n- **Name:** Test Agent\n")
    (vault / "AGENTS.md").write_text("# Workspace Rules\n\nBe helpful.\n")
    (vault / "USER.md").write_text("# User\n\nDeveloper, terse responses.\n")
    (vault / "SOUL.md").write_text("# Soul\n\nCurious.\n")
    VaultRepo(vault).ensure_repo()
    return vault


@pytest.fixture
def tmp_vault_repo(tmp_vault: Path) -> VaultRepo:
    return VaultRepo(tmp_vault)


# ============================================================
# Settings
# ============================================================


@pytest.fixture
def test_settings(tmp_vault: Path, tmp_path: Path) -> Settings:
    """Settings safe for unit/integration tests — no external services hit.

    Explicit ``None`` overrides for MCP and Langfuse keys block the local
    ``.env`` from leaking into tests.
    """
    return Settings(
        vault_path=tmp_vault,
        agent_id="test-agent",
        openai_api_key="sk-test-not-real",
        openai_model="gpt-test",
        openai_base_url=None,
        telegram_bot_token="test-token",
        checkpoint_db=tmp_path / "checkpoints.db",
        max_retries=0,
        retry_base_delay=0.0,
        mcp_gateway_url=None,
        mcp_agent_key=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )


# ============================================================
# Tracing — kill Langfuse for every test by default
# ============================================================


@pytest.fixture(autouse=True)
def _disable_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force Langfuse keys empty so the tracing handler is a no-op."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    from commandclaw.tracing.langfuse_tracing import reset_default_manager

    reset_default_manager()


# ============================================================
# Persistence — fresh AsyncSqliteSaver per test
# ============================================================


@pytest.fixture
async def checkpointer(test_settings: Settings):
    """Open a fresh AsyncSqliteSaver and tear it down after the test."""
    from commandclaw.agent.persistence import open_checkpointer

    saver, close = await open_checkpointer(test_settings)
    try:
        yield saver
    finally:
        await close()


# ============================================================
# Fake LLM — factory for GenericFakeChatModel
# ============================================================


class _FakeChatModelWithTools:
    """Internal sentinel — see ``fake_llm`` fixture."""


@pytest.fixture
def fake_llm() -> Callable[[Iterable[AIMessage]], BaseChatModel]:
    """Build a fake chat model that yields the given AIMessages in order.

    ``langchain_core``'s ``GenericFakeChatModel`` raises ``NotImplementedError``
    from ``bind_tools``, which ``create_agent`` always calls. We subclass it
    once and make ``bind_tools`` a no-op so the fake works inside the agent.

    Usage::

        llm = fake_llm([AIMessage(content="hi")])
        agent, _ = await build_agent_graph(settings, model=llm, checkpointer=ck)
    """
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    class _AgentFakeChatModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):  # type: ignore[override]
            return self

    def _make(responses: Iterable[AIMessage]) -> BaseChatModel:
        return _AgentFakeChatModel(messages=iter(list(responses)))

    return _make


# ============================================================
# Agent context helper
# ============================================================


@pytest.fixture
def agent_context(test_settings: Settings):
    """A ready-to-pass CommandClawContext for invoking the graph."""
    from commandclaw.agent.graph import CommandClawContext

    return CommandClawContext(
        vault_path=str(test_settings.vault_path),
        agent_id=test_settings.agent_id,
        api_key=test_settings.openai_api_key,
        user_id="test-user",
        session_id="test-session",
    )
