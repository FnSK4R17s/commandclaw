# Anti-patterns

Append-only log of mistakes agents have made in this repo and the correct
approach. **Newest first.** Read this file before starting non-trivial work.

Format per entry:

```
## <YYYY-MM-DD> — <one-line summary>

**What went wrong:** <what the agent did>

**Correct approach:** <what to do instead>

**Context:** <optional — file path, command, or scenario>
```

Use `${CLAUDE_SKILL_DIR}/scripts/log-antipattern.sh` (from the
`repo-best-practices` skill) to append entries — keeps formatting consistent
and ordering correct.

---

<!-- New entries go below this line, newest first. -->

## 2026-04-25 — TDD skill skipped plan-feature reference files before slicing

**What went wrong:** `/tdd implement plan/message-queue/04-backlog-item.md` was invoked. The agent read only the backlog item and the codebase, then proposed 10 TDD slices. It never read `01-research.md`, `02-requirements.md`, or `03-deep-research.md` — despite the backlog item's References section explicitly listing them under "The implementing agent should read these before starting." The deep-research file contained PTB-specific integration details: `block=False` on MessageHandler to enable concurrent `/stop` dispatch, `group=-1` on the `/stop` CommandHandler for priority, and the `_post_init` wiring that creates a Dispatcher with a `process_fn_factory` and stores it in `bot_data["dispatcher"]`. All three were missed in slicing, leaving the queue infrastructure disconnected from the PTB application lifecycle.

**Correct approach:** When the TDD skill receives a backlog item (04-backlog-item.md) as input, read its References section and load all linked stage files (01-research, 02-requirements, 03-deep-research) before proposing slices. These files contain codebase context, acceptance criteria, resolved design questions, and integration details that the backlog item intentionally omits. Skipping them causes incomplete slicing. Derive behaviors-to-test from acceptance criteria in 02-requirements.md and cross-check against resolved questions in 03-deep-research.md.

**Context:** `plan/message-queue/04-backlog-item.md` lines 143-148, `/tdd` skill SKILL.md Planning section

---


## 2026-04-23 — Regex `rm\s+-[a-zA-Z]*r` silently allowed `rm -rf`

**What went wrong:** The dangerous-command guardrail regex required the flag block to *end* in `r`, so it caught `rm -r` and `rm -fr` but missed the most common form `rm -rf`. No tests existed, so the hole shipped.

**Correct approach:** Use `rm\s+-[a-zA-Z]*r[a-zA-Z]*` — match any flag block that *contains* `r`. More importantly, every regex in `guardrails/engine.py` ships under a parametrized unit test. Adding a pattern means adding a `pytest.mark.parametrize` row in [tests/unit/test_guardrails_engine.py](tests/unit/test_guardrails_engine.py) — both positive and negative cases.

**Context:** [src/commandclaw/guardrails/engine.py:96](src/commandclaw/guardrails/engine.py#L96)

## 2026-04-23 — Smuggling runtime context through `TypedDict` state with `_` prefix

**What went wrong:** `state.get("_vault_path")` and `state.get("_api_key")` in `agent/graph.py` nodes. Underscore prefix signaled "internal" but values still flow through checkpointer serialization, leak into traces, and pollute the state schema. A `CommandClawContext` dataclass was defined alongside but never wired up.

**Correct approach:** Per LangGraph `state.md` and LangChain `context-engineering.md`, runtime context (paths, API keys, settings) belongs in `configurable` (graph) or `Context` (agent) — not `TypedDict` state. Pass via `config={"configurable": {"vault_path": ..., "api_key": ...}}` and read via `RunnableConfig` in nodes. Reserve state for data that genuinely flows between nodes.

**Context:** [src/commandclaw/agent/graph.py](src/commandclaw/agent/graph.py)

## 2026-04-23 — Async cleanup coroutine discarded in `finally` block

**What went wrong:** `agent/runtime.py::create_agent` returned `cleanup` as `async def`, but `telegram/bot.py` called `cleanup_fn()` synchronously inside the `run_polling` `finally` block. The coroutine was never awaited — MCP disconnect and Langfuse `flush()` silently never ran. Lost traces on every shutdown; lingering MCP HTTP connections.

**Correct approach:** For python-telegram-bot, register async teardown via `ApplicationBuilder().post_shutdown(callback)` (see `python-telegram-bot/references/application-lifecycle.md`). Never `cleanup_fn()` an async function from sync context. If the cleanup must stay sync at the call site, wrap with `asyncio.run` *only* when no loop is already running — but the PTB hook is the right answer.

**Context:** [src/commandclaw/telegram/bot.py:63](src/commandclaw/telegram/bot.py#L63), [src/commandclaw/agent/runtime.py:113](src/commandclaw/agent/runtime.py#L113)

## 2026-04-23 — `MemorySaver` checkpointer in production Telegram bot

**What went wrong:** Both `agent/graph.py` and `agent/runtime.py` used `langgraph.checkpoint.memory.MemorySaver()` for a long-running Telegram agent. Conversation history evaporated on every restart. The repo already declared `langgraph-checkpoint-sqlite>=3` as a dependency but never imported it.

**Correct approach:** `MemorySaver` is for tests and notebooks only. Production agents need durable checkpointers — `SqliteSaver` (single-instance), `PostgresSaver` (multi-replica), or LangGraph Cloud. See LangGraph `persistence.md`. For CommandClaw, store the SQLite file under the vault so conversation state is git-trackable and survives container restarts.

**Context:** [src/commandclaw/agent/graph.py:391](src/commandclaw/agent/graph.py#L391), [src/commandclaw/agent/runtime.py:107](src/commandclaw/agent/runtime.py#L107)

## 2026-04-23 — Manual Langfuse spans duplicating `CallbackHandler` coverage

**What went wrong:** Wrapped graph nodes with `lf.start_as_current_observation(...)` *and* registered `langfuse.langchain.CallbackHandler` on the same invocation. CallbackHandler already emits a span tree for every LangGraph node — manual spans nested under it produce duplicate observations and inflate token-cost rollups in the dashboard.

**Correct approach:** Pick one. For LangChain/LangGraph code paths, `CallbackHandler` is the recommended primitive (see `langfuse-tracing/SKILL.md` §2). Use manual `start_as_current_observation` only for non-LangChain code that the callback can't see (raw HTTP calls, custom event loops, etc.).

**Context:** [src/commandclaw/agent/graph.py:121](src/commandclaw/agent/graph.py#L121), [src/commandclaw/agent/graph.py:162](src/commandclaw/agent/graph.py#L162), [src/commandclaw/agent/graph.py:423](src/commandclaw/agent/graph.py#L423)

## 2026-04-23 — `create_react_agent` (LangGraph primitive) when `langchain>=1.2` is pinned

**What went wrong:** Both agent paths imported `from langgraph.prebuilt import create_react_agent` despite `langchain>=1.2` being a declared dependency. Missed out on the LangChain v1 middleware system (`@before_model`, `@after_model`, built-in `PIIMiddleware`) and built bespoke guardrail nodes instead.

**Correct approach:** Use `langchain.agents.create_agent` for the high-level agent factory in v1+. Push guardrails into middleware so the inner agent's tool loop, structured output, and message normalization come for free. Reserve `create_react_agent` for cases where you genuinely need direct LangGraph control. See `langchain/SKILL.md` "Anti-recommendations".

**Context:** [src/commandclaw/agent/graph.py:24](src/commandclaw/agent/graph.py#L24), [src/commandclaw/agent/runtime.py:32](src/commandclaw/agent/runtime.py#L32)

## 2026-04-23 — Two parallel agent implementations, hot path on the legacy one

**What went wrong:** `agent/runtime.py` (prompt-heavy AgentExecutor-style) and `agent/graph.py` (newer StateGraph) coexisted. `telegram/handlers.py` → `agent/retry.py` → `runtime.invoke_agent` was the live path; `graph.py` was effectively dead. New features (guardrails, MCP lazy-load) only landed in the dead path.

**Correct approach:** When refactoring an agent loop, delete the old path in the same PR that adds the new one. Forks of the entry point silently rot. If a parallel path is genuinely needed during migration, gate it behind a single feature flag that's removed within one release.

**Context:** [src/commandclaw/agent/runtime.py](src/commandclaw/agent/runtime.py), [src/commandclaw/agent/graph.py](src/commandclaw/agent/graph.py), [src/commandclaw/agent/retry.py](src/commandclaw/agent/retry.py)

