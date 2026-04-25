"""E2e tests — real LLM, real Langfuse, real MCP gateway.

Run with: ./.venv/bin/pytest -m e2e -v
Keys loaded from .env via conftest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from commandclaw.config import Settings

pytestmark = pytest.mark.e2e


def _load_settings() -> Settings:
    return Settings()


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def e2e_vault(tmp_path: Path) -> Path:
    """Minimal vault for e2e tests."""
    vault = tmp_path / "e2e-vault"
    vault.mkdir()
    (vault / "IDENTITY.md").write_text("# Identity\n\n- **Name:** E2E Bot\n")
    (vault / "AGENTS.md").write_text("# Rules\n\nBe concise.\n")
    (vault / "USER.md").write_text("# User\n\nTester.\n")
    (vault / "SOUL.md").write_text("# Soul\n\nDiligent.\n")
    from commandclaw.vault.git_ops import VaultRepo

    VaultRepo(vault).ensure_repo()
    return vault


@pytest.fixture
def e2e_settings(e2e_vault: Path, tmp_path: Path) -> Settings:
    """Settings loaded from .env but with a temp vault and checkpointer."""
    settings = _load_settings()
    settings.vault_path = e2e_vault
    settings.checkpoint_db = tmp_path / "e2e-ck.db"
    settings.agent_id = "e2e-test"
    settings.max_retries = 0
    settings.mcp_gateway_url = None
    return settings


# ============================================================
# 1. Real LLM round-trip
# ============================================================



async def test_real_llm_responds(e2e_settings: Settings) -> None:
    """Send a trivial message to the real LLM and get a coherent response."""
    from commandclaw.agent.graph import build_agent_graph, invoke_agent
    from commandclaw.agent.persistence import open_checkpointer

    saver, close = await open_checkpointer(e2e_settings)
    try:
        agent, _ = await build_agent_graph(e2e_settings, checkpointer=saver)
        result = await invoke_agent(
            agent, "Reply with exactly: PONG", e2e_settings,
            session_id="e2e-ping", user_id="e2e",
        )
        assert result.success, f"Agent failed: {result.error}"
        assert len(result.output) > 0
    finally:
        await close()


# ============================================================
# 2. Real tool call — LLM reads a vault file
# ============================================================



async def test_real_llm_uses_file_read(e2e_settings: Settings) -> None:
    """Ask the LLM to read IDENTITY.md — it should use file_read and return content."""
    from commandclaw.agent.graph import build_agent_graph, invoke_agent
    from commandclaw.agent.persistence import open_checkpointer

    saver, close = await open_checkpointer(e2e_settings)
    try:
        agent, _ = await build_agent_graph(e2e_settings, checkpointer=saver)
        result = await invoke_agent(
            agent,
            "Use the file_read tool to read IDENTITY.md and tell me the agent's name.",
            e2e_settings,
            session_id="e2e-tool", user_id="e2e",
        )
        assert result.success, f"Agent failed: {result.error}"
        assert "E2E Bot" in result.output
    finally:
        await close()


# ============================================================
# 3. Langfuse tracing — handler creation
# ============================================================



def test_langfuse_handler_created(e2e_settings: Settings) -> None:
    """With real Langfuse keys, create_langfuse_handler returns a real handler."""
    from commandclaw.tracing.langfuse_tracing import TracingManager, reset_default_manager

    reset_default_manager()

    settings = _load_settings()
    settings.agent_id = "e2e-test"

    mgr = TracingManager(settings)
    handler = mgr.create_handler(session_id="e2e", user_id="e2e")
    assert handler is not None
    mgr.flush()


# ============================================================
# 4. MCP gateway — connect and list tools (requires running gateway)
# ============================================================


@pytest.mark.mcp
async def test_mcp_gateway_lists_tools() -> None:
    """Connect to the real MCP gateway, list tools, verify at least one exists."""
    from commandclaw.mcp.client import MCPClient

    settings = _load_settings()
    client = MCPClient(
        gateway_url=settings.mcp_gateway_url,
        agent_id=settings.agent_id or "test-agent",
        agent_key=settings.mcp_agent_key or "",
    )
    await client.connect()
    try:
        tools = await client.list_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0, "Expected at least one MCP tool from the gateway"
    finally:
        await client.disconnect()


# ============================================================
# 5. Multi-turn conversation with real LLM
# ============================================================



async def test_real_llm_multi_turn(e2e_settings: Settings) -> None:
    """Two-turn conversation with real LLM — second turn references the first."""
    from commandclaw.agent.graph import build_agent_graph, invoke_agent
    from commandclaw.agent.persistence import open_checkpointer

    saver, close = await open_checkpointer(e2e_settings)
    try:
        agent, _ = await build_agent_graph(e2e_settings, checkpointer=saver)

        r1 = await invoke_agent(
            agent, "Remember the secret word: PINEAPPLE", e2e_settings,
            session_id="e2e-multi", user_id="e2e",
        )
        assert r1.success

        r2 = await invoke_agent(
            agent, "What was the secret word I just told you?", e2e_settings,
            session_id="e2e-multi", user_id="e2e",
        )
        assert r2.success
        assert "PINEAPPLE" in r2.output.upper()
    finally:
        await close()
