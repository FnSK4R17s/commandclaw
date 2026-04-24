"""Tests for commandclaw.agent.context — pure data types, no framework deps."""

from __future__ import annotations

from commandclaw.agent.context import AgentResult, CommandClawContext


class TestCommandClawContext:
    def test_required_fields(self) -> None:
        ctx = CommandClawContext(vault_path="/v", agent_id="a1")
        assert ctx.vault_path == "/v"
        assert ctx.agent_id == "a1"

    def test_optional_fields_default_none(self) -> None:
        ctx = CommandClawContext(vault_path="/v", agent_id="a1")
        assert ctx.api_key is None
        assert ctx.user_id is None
        assert ctx.session_id is None

    def test_all_fields(self) -> None:
        ctx = CommandClawContext(
            vault_path="/v", agent_id="a1",
            api_key="sk-x", user_id="u1", session_id="s1",
        )
        assert ctx.api_key == "sk-x"
        assert ctx.user_id == "u1"
        assert ctx.session_id == "s1"


class TestAgentResult:
    def test_success(self) -> None:
        r = AgentResult(output="hi", success=True)
        assert r.output == "hi"
        assert r.success is True
        assert r.error is None

    def test_failure(self) -> None:
        r = AgentResult(output="", success=False, error="boom")
        assert r.success is False
        assert r.error == "boom"
