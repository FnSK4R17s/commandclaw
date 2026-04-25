"""Agent-tier tests: tool calls and guardrails through the compiled graph.

Each test scripts a fake LLM, builds the real agent graph, and asserts on
the final message state. No real LLM calls, deterministic, fast.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from commandclaw.agent.graph import build_agent_graph, invoke_agent

pytestmark = pytest.mark.agent


# ============================================================
# Shared guardrail passthrough
# ============================================================


def _bypass_guardrails(monkeypatch):
    """Disable both guardrails so the LLM's scripted responses flow through."""

    async def passthrough(_msg: str, api_key: str | None = None) -> list[str]:
        return []

    monkeypatch.setattr("commandclaw.guardrails.engine.check_input", passthrough)
    monkeypatch.setattr("commandclaw.guardrails.engine.check_output", passthrough)


# ============================================================
# Output guardrail — blocks secret in LLM response
# ============================================================


async def test_output_guardrail_blocks_secret_in_response(
    test_settings,
    fake_llm,
    checkpointer,
    agent_context,
    monkeypatch,
):
    """LLM returns a secret pattern — output guardrail replaces it."""

    async def passthrough(_msg: str, api_key: str | None = None) -> list[str]:
        return []

    async def fake_check_output(_msg: str, api_key: str | None = None) -> list[str]:
        return ["secret_leaked: sk-"]

    monkeypatch.setattr("commandclaw.guardrails.engine.check_input", passthrough)
    monkeypatch.setattr("commandclaw.guardrails.engine.check_output", fake_check_output)

    llm = fake_llm([
        AIMessage(content="Here is the key: sk-" + "a" * 30),
    ])
    agent, _ = await build_agent_graph(
        test_settings, checkpointer=checkpointer, model=llm,
    )

    result = await agent.ainvoke(
        {"messages": [HumanMessage("show me the API key")]},
        config={"configurable": {"thread_id": "t-output-guard"}},
        context=agent_context,
    )

    final = result["messages"][-1]
    assert isinstance(final, AIMessage)
    assert "sensitive information" in final.content.lower()
    assert "sk-" not in final.content


# ============================================================
# Bash tool — LLM calls bash, output flows back
# ============================================================


async def test_agent_invokes_bash_tool(
    test_settings,
    fake_llm,
    checkpointer,
    agent_context,
    monkeypatch,
):
    """LLM calls the bash tool; command output appears in ToolMessage."""
    _bypass_guardrails(monkeypatch)

    llm = fake_llm([
        AIMessage(
            content="",
            tool_calls=[{
                "name": "bash",
                "args": {"command": "echo hello-from-bash"},
                "id": "call_bash_1",
            }],
        ),
        AIMessage(content="The command printed: hello-from-bash"),
    ])
    agent, _ = await build_agent_graph(
        test_settings, checkpointer=checkpointer, model=llm,
    )

    result = await agent.ainvoke(
        {"messages": [HumanMessage("run echo hello-from-bash")]},
        config={"configurable": {"thread_id": "t-bash"}},
        context=agent_context,
    )

    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    assert tool_msgs
    assert "hello-from-bash" in tool_msgs[0].content


# ============================================================
# File write + read round-trip through the agent
# ============================================================


async def test_agent_writes_then_reads_file(
    test_settings,
    fake_llm,
    checkpointer,
    agent_context,
    monkeypatch,
):
    """LLM writes a file, then reads it back. Both tool results are correct."""
    _bypass_guardrails(monkeypatch)

    llm = fake_llm([
        AIMessage(
            content="",
            tool_calls=[{
                "name": "file_write",
                "args": {"file_path": "test-note.md", "content": "agent wrote this"},
                "id": "call_write",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "file_read",
                "args": {"file_path": "test-note.md"},
                "id": "call_read",
            }],
        ),
        AIMessage(content="Done. The file contains: agent wrote this"),
    ])
    agent, _ = await build_agent_graph(
        test_settings, checkpointer=checkpointer, model=llm,
    )

    result = await agent.ainvoke(
        {"messages": [HumanMessage("write and read test-note.md")]},
        config={"configurable": {"thread_id": "t-write-read"}},
        context=agent_context,
    )

    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    assert len(tool_msgs) == 2
    assert "Wrote" in tool_msgs[0].content
    assert "agent wrote this" in tool_msgs[1].content


# ============================================================
# File list through the agent
# ============================================================


async def test_agent_invokes_file_list_tool(
    test_settings,
    fake_llm,
    checkpointer,
    agent_context,
    monkeypatch,
):
    """LLM calls file_list on the vault root; sees the identity files."""
    _bypass_guardrails(monkeypatch)

    llm = fake_llm([
        AIMessage(
            content="",
            tool_calls=[{
                "name": "file_list",
                "args": {"directory": "."},
                "id": "call_ls",
            }],
        ),
        AIMessage(content="Found the vault files."),
    ])
    agent, _ = await build_agent_graph(
        test_settings, checkpointer=checkpointer, model=llm,
    )

    result = await agent.ainvoke(
        {"messages": [HumanMessage("list vault files")]},
        config={"configurable": {"thread_id": "t-list"}},
        context=agent_context,
    )

    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    assert tool_msgs
    assert "IDENTITY.md" in tool_msgs[0].content


# ============================================================
# invoke_agent retry — first call fails, second succeeds
# ============================================================


async def test_invoke_agent_retries_on_failure(
    test_settings,
    checkpointer,
    monkeypatch,
):
    """invoke_agent retries after a transient failure."""
    _bypass_guardrails(monkeypatch)

    test_settings.max_retries = 1
    test_settings.retry_base_delay = 0.0

    call_count = 0

    class _FlakeyAgent:
        async def ainvoke(self, inputs, config=None, context=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient failure")
            return {"messages": [AIMessage(content="recovered")]}

    result = await invoke_agent(
        _FlakeyAgent(),
        "hello",
        test_settings,
        session_id="retry-test",
    )

    assert result.success is True
    assert result.output == "recovered"
    assert call_count == 2


async def test_invoke_agent_exhausts_retries(
    test_settings,
    checkpointer,
    monkeypatch,
):
    """invoke_agent returns failure after exhausting all retries."""
    _bypass_guardrails(monkeypatch)

    test_settings.max_retries = 1
    test_settings.retry_base_delay = 0.0

    class _AlwaysFails:
        async def ainvoke(self, inputs, config=None, context=None):
            raise RuntimeError("permanent failure")

    result = await invoke_agent(
        _AlwaysFails(),
        "hello",
        test_settings,
        session_id="exhaust-test",
    )

    assert result.success is False
    assert "permanent failure" in result.error
