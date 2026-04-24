"""Unit tests for ``commandclaw.agent.tools.system_info``.

Covers:
* Standard vs admin mode rendering, env-var driven.
* Available / missing command discovery via ``shutil.which``.
* Gateway capabilities fetch via ``httpx.MockTransport`` — no network.
"""

from __future__ import annotations

import httpx
import pytest

from commandclaw.agent.tools import system_info as si

# ============================================================
# Tool body — env vars + shutil.which
# ============================================================


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wipe the env vars system_info reads so each test sets them explicitly."""
    for key in (
        "COMMANDCLAW_ADMIN_MODE",
        "COMMANDCLAW_AGENT_ID",
        "COMMANDCLAW_MCP_GATEWAY_URL",
    ):
        monkeypatch.delenv(key, raising=False)


async def test_standard_mode_lists_restrictions(
    monkeypatch: pytest.MonkeyPatch, clean_env
) -> None:
    monkeypatch.setenv("COMMANDCLAW_AGENT_ID", "calm-fox-0042")
    monkeypatch.setattr(si.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

    tool = si.create_system_info_tool()
    output = await tool.ainvoke({})

    assert "Agent ID: calm-fox-0042" in output
    assert "Mode: STANDARD" in output
    assert "Restrictions:" in output
    assert "ADMIN" not in output


async def test_admin_mode_lists_capabilities(
    monkeypatch: pytest.MonkeyPatch, clean_env
) -> None:
    monkeypatch.setenv("COMMANDCLAW_ADMIN_MODE", "1")
    monkeypatch.setenv("COMMANDCLAW_AGENT_ID", "bold-bat-0001")
    monkeypatch.setattr(si.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

    tool = si.create_system_info_tool()
    output = await tool.ainvoke({})

    assert "Mode: ADMIN" in output
    assert "Capabilities:" in output
    assert "Restrictions:" not in output


async def test_lists_available_and_missing_commands(
    monkeypatch: pytest.MonkeyPatch, clean_env
) -> None:
    available = {"git", "python3", "curl"}
    monkeypatch.setattr(
        si.shutil, "which", lambda cmd: "/usr/bin/x" if cmd in available else None
    )

    tool = si.create_system_info_tool()
    output = await tool.ainvoke({})

    assert "Available: git, python3, curl" in output
    assert "Missing: node, npm, npx" in output


async def test_no_missing_section_when_all_commands_present(
    monkeypatch: pytest.MonkeyPatch, clean_env
) -> None:
    monkeypatch.setattr(si.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    tool = si.create_system_info_tool()
    output = await tool.ainvoke({})
    assert "Missing:" not in output


# ============================================================
# Gateway capabilities fetch
# ============================================================


async def test_fetch_gateway_capabilities_returns_none_when_no_url() -> None:
    assert await si._fetch_gateway_capabilities("", "agent-1") is None


async def test_fetch_gateway_capabilities_returns_dict_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/sessions" and request.method == "POST":
            return httpx.Response(201, json={"phantom_token": "tok-xyz"})
        if path == "/capabilities" and request.method == "GET":
            captured["auth"] = request.headers.get("authorization", "")
            return httpx.Response(200, json={
                "mode": "admin",
                "roles": ["builder"],
                "allowed_tools": ["search", "fetch"],
                "rate_limit": {"requests_per_minute": 60},
            })
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_async_client)

    caps = await si._fetch_gateway_capabilities("http://gateway:8420/mcp", "agent-1")
    assert caps == {
        "mode": "admin",
        "roles": ["builder"],
        "allowed_tools": ["search", "fetch"],
        "rate_limit": {"requests_per_minute": 60},
    }
    assert captured["auth"] == "Bearer tok-xyz"


async def test_fetch_gateway_capabilities_returns_none_on_session_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_async_client)

    caps = await si._fetch_gateway_capabilities("http://gateway/mcp", "agent-1")
    assert caps is None


async def test_fetch_gateway_capabilities_swallows_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_async_client)

    caps = await si._fetch_gateway_capabilities("http://gateway/mcp", "agent-1")
    assert caps is None


async def test_tool_uses_gateway_caps_when_available(
    monkeypatch: pytest.MonkeyPatch, clean_env
) -> None:
    """When the gateway answers, the rendered output reflects those caps."""

    async def fake_fetch(_url: str, _agent_id: str) -> dict | None:
        return {
            "mode": "admin",
            "roles": ["builder", "ops"],
            "allowed_tools": ["search"],
            "rate_limit": {"requests_per_minute": 30},
        }

    monkeypatch.setenv("COMMANDCLAW_MCP_GATEWAY_URL", "http://gateway/mcp")
    monkeypatch.setenv("COMMANDCLAW_AGENT_ID", "fast-deer-0003")
    monkeypatch.setattr(si, "_fetch_gateway_capabilities", fake_fetch)
    monkeypatch.setattr(si.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

    tool = si.create_system_info_tool()
    output = await tool.ainvoke({})

    assert "Mode: ADMIN" in output
    assert "Roles: builder, ops" in output
    assert "Allowed tool servers: search" in output
    assert "Rate limit: 30 req/min" in output
