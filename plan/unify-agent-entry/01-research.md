# Stage 1 — Research

> Observation only. No design, no requirements, no solutions.

**Feature:** unify-agent-entry
**One-liner:** Collapse the two parallel agent implementations — agent/runtime.py and agent/graph.py — into one canonical entry point exposed via agent/__init__.py.
**Date:** 2026-04-22

## Existing surface area

### Core agent files

- `src/commandclaw/agent/runtime.py` — bare LangGraph ReAct agent. Defines `create_agent(settings)` (lines 24–129), `invoke_agent(...)` (lines 132–236), and `AgentResult` dataclass (lines 15–20). `create_agent` returns `(agent_executor, cleanup_fn)`. Uses `MemorySaver` checkpointer. Calls `build_system_prompt` from `agent/prompt.py` on every invocation. Loads MCP tools at startup (not lazily).
- `src/commandclaw/agent/graph.py` — guardrailed LangGraph StateGraph. Defines `build_agent_graph(settings)` (lines 207–395) and `TracedGraph` wrapper class (lines 398–463). Returns a `TracedGraph`-wrapped compiled graph. Uses lazy MCP tool loading on first invocation. Does NOT call `agent/prompt.py` — builds a minimal identity-only prompt inline in the `load_identity` node (lines 66–98). Sets `max_tokens` based on model name (lines 218–227). Adds two extra tools not in runtime: `create_browse_skills_tool()` and `create_install_skill_tool()`.
- `src/commandclaw/agent/__init__.py` — re-exports only runtime symbols: `AgentResult`, `create_agent`, `invoke_agent`, `invoke_with_retry`. `build_agent_graph` is completely absent from this file.
- `src/commandclaw/agent/retry.py` — `invoke_with_retry(agent_executor, message, settings, ...)`. Imports `invoke_agent` and `AgentResult` directly from `commandclaw.agent.runtime` (line 9). Calls `invoke_agent` in a retry loop.
- `src/commandclaw/agent/prompt.py` — `build_system_prompt(agent_config, vault_identity, long_term_memory, daily_notes, skills)`. Assembles full system prompt from vault state (AGENTS.md, SOUL.md, IDENTITY.md, USER.md, TOOLS.md, HEARTBEAT.md, long-term memory, daily notes, skills). Used exclusively by `runtime.py`'s `invoke_agent`. Not used by `graph.py` at all.

### CLI and Telegram wiring

- `src/commandclaw/__main__.py` — splits the two agents by mode:
  - `chat` and `bootstrap` modes (lines 59–60, 129–229): call `build_agent_graph(settings)` from `commandclaw.agent.graph` (line 133). Invoke via `graph.ainvoke(...)` with full `CommandClawState` dict (lines 190–204), passing `_vault_path` as an out-of-band key.
  - `telegram` mode (lines 63–68): calls `create_agent(settings)` from `commandclaw.agent.runtime` (line 63, imported locally). Passes `agent_executor` and `cleanup_fn` to `start_bot`.
- `src/commandclaw/telegram/bot.py` — `start_bot(agent_executor, settings, cleanup_fn)`. Accepts whatever `agent_executor` was passed. Registers handlers and starts polling.
- `src/commandclaw/telegram/handlers.py` — `create_message_handler(agent_executor, settings)`. Calls `invoke_with_retry(agent_executor, text, settings, session_id=..., user_id=...)` (line 64). Returns `AgentResult`. Depends on the runtime's `AgentResult.success` / `AgentResult.output` / `AgentResult.error` interface.

### Tests

- `tests/test_agent_retry.py` — tests `invoke_with_retry` only. Imports `invoke_with_retry` from `commandclaw.agent.retry` and `AgentResult` from `commandclaw.agent.runtime`. Patches `commandclaw.agent.retry.invoke_agent`. No tests for `create_agent` or `build_agent_graph`.
- `tests/test_tools_bash.py`, `test_tools_files.py`, `test_vault_*.py` — test tools and vault ops independently, no agent-level tests.
- `graph.py` has zero test coverage.

## Relevant patterns already in the codebase

**Runtime invoke contract** (`src/commandclaw/agent/runtime.py`, lines 132–236): callers pass `(agent_executor, message, settings, session_id, user_id)` and receive `AgentResult(output, success, error)`. This is the contract that `retry.py` and `telegram/handlers.py` both depend on — it is the existing "external interface."

**Graph invoke contract** (`src/commandclaw/__main__.py`, lines 190–204): callers construct a full `CommandClawState` dict including `_vault_path` as an undeclared extra key (not in the `CommandClawState` TypedDict at lines 37–48 of `graph.py`), pass it to `graph.ainvoke(...)`, and manually extract the last `AIMessage` from `result["messages"]`. This is a wider, more complex calling convention used only in the chat/bootstrap REPL.

**TracedGraph wrapper** (`src/commandclaw/agent/graph.py`, lines 398–463): wraps the compiled graph to add a Langfuse trace context around every `ainvoke`. The runtime's `invoke_agent` does the equivalent tracing inline via a `langfuse_ctx` context manager (lines 182–215).

**Lazy vs eager MCP loading**: `graph.py` loads MCP tools lazily on first invocation using an `asyncio.Lock` (lines 311–330). `runtime.py` loads them eagerly at startup in `create_agent` (lines 79–92).

**Prompt assembly strategy divergence**: `runtime.py` calls `build_system_prompt` from `agent/prompt.py` on every invocation, loading vault state fresh each time (identity, memory, skills, daily notes, SOUL.md, TOOLS.md, HEARTBEAT.md). `graph.py`'s `load_identity` node reads only `IDENTITY.md`, `AGENTS.md`, and `USER.md` from the vault path, building a minimal prompt inline — it omits SOUL.md, TOOLS.md, HEARTBEAT.md, long-term memory, daily notes, and skills listing.

**Tool set divergence**: `graph.py` adds `create_browse_skills_tool()` and `create_install_skill_tool()` (lines 248–252) not present in `runtime.py`. `runtime.py` has 10 tools; `graph.py` has 12 tools.

**max_tokens logic**: `graph.py` sets `max_tokens` on the LLM based on model name (lines 218–227). `runtime.py` does not set `max_tokens` at all.

## Constraints discovered

- **`AgentResult` interface is load-bearing**: `telegram/handlers.py` and `retry.py` both depend on `AgentResult.success`, `AgentResult.output`, `AgentResult.error`. Any unified entry point must either return `AgentResult` or provide a compatible adapter.
- **`invoke_with_retry` is hardwired to `invoke_agent`**: `retry.py` line 9 imports `invoke_agent` directly from `commandclaw.agent.runtime`, and patches at `commandclaw.agent.retry.invoke_agent` in tests. The retry wrapper cannot currently route to `build_agent_graph` at all.
- **Telegram mode does not use guardrails today**: the runtime path (Telegram) has no input/output guardrail nodes. Only the chat/bootstrap path (graph) does.
- **`_vault_path` is passed as an undeclared TypedDict key**: `graph.py`'s `load_identity` node reads `state.get("_vault_path", "/workspace")`. This key is not declared in `CommandClawState`. Similarly `_api_key` is accessed by `input_guardrails` (line 114) and `output_guardrails` (line 156) but never injected by any caller — the `__main__.py` call site (lines 190–204) does not pass `_api_key`, meaning guardrails always call `check_input`/`check_output` with `api_key=None`.
- **Checkpointer placement differs**: `runtime.py` attaches `MemorySaver` to the inner `create_react_agent` call (line 110). `graph.py` attaches `MemorySaver` to the outer `StateGraph` compile (line 392). The thread_id format also differs: runtime uses `"{agent_id}/{session_id}"` (line 174); graph uses `"{agent_id}/inner"` for the inner agent (line 344) and the outer graph receives thread_id from the caller's config.
- **`ruff` rules apply**: `target-version = "py311"`, `line-length = 100`, rules `E,F,I,N,W,UP`. Run `./.venv/bin/ruff check .` before commit.
- **Async tests only**: `asyncio_mode = "auto"`. No `@pytest.mark.asyncio` decorator needed; write `async def test_*` directly.
- **Strict markers**: any new `@pytest.mark.foo` must be registered in `pyproject.toml` before use.
- **Python env**: always use `./.venv/bin/<tool>`.
- **`graph.py` has no tests**: a unification that touches graph behavior has zero test coverage to catch regressions.

## qmd findings (if enabled)

Searches run on collections `shikhar-wiki` and `shikhar-raw` with queries:
- `{type: 'lex', query: 'canonical entry point module split brain'}`
- `{type: 'vec', query: 'two parallel implementations of the same feature merging into one'}`
- `intent: 'choosing canonical entry point between two parallel implementations'`

No relevant hits. Top result (`shikhar-wiki/templates/concept.md`, score 0.88) is a blank wiki template — not applicable. All other results were template files, log entries, or unrelated articles. Nothing in the personal wiki addresses module consolidation patterns.

## Unknowns surfaced

- **Who owns cleanup for the graph path?** `runtime.py`'s `create_agent` returns a `cleanup_fn` that disconnects MCP and flushes tracing. `build_agent_graph` returns no cleanup function — tracing is flushed only in `_chat_loop`'s `finally` block. If the graph becomes the canonical implementation, there is no cleanup contract defined for it.
- **Is `_api_key` ever intended to be injected?** The guardrail nodes read `state.get("_api_key")` but no caller sets it. It is unknown whether this was an in-progress feature, a copy-paste artifact, or intentional (falling back to env var inside `check_input`/`check_output`).
- **What does `check_input`/`check_output` do with `api_key=None`?** The guardrails engine (`src/commandclaw/guardrails/engine.py`) behaviour with a null api_key is not verified — it may fall back to `OPENAI_API_KEY` env var or it may no-op.
- **Are the two tool sets intentionally different?** `browse_skills` and `install_skill` in `graph.py` but absent from `runtime.py` — unclear if this is an oversight or a deliberate split (e.g., those tools only make sense in the interactive chat context).
- **Thread/session continuity across the boundary**: Telegram sessions use `session_id=str(chat_id)` yielding thread_id `"{agent_id}/{chat_id}"` via `invoke_agent`. The graph path hardcodes `"{agent_id}/inner"` for the inner agent and `"{agent_id}/cli"` for the outer. Merging the two would require deciding a single thread_id scheme.
- **`TracedGraph.ainvoke` signature mismatch**: `TracedGraph.ainvoke(input_, config, **kwargs)` takes a positional `input_` (not `input`). The underlying compiled graph uses `input`. This is an inconsistency that would affect any adapter wrapping the graph in the runtime's calling convention.
- **`__main__.py` comment at line 63**: `# Telegram mode still uses old runtime for now` — this is an explicit deferral comment, confirming the split is known technical debt, not accidental.
