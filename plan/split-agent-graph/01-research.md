# Stage 1 — Research

> Observation only. No design, no requirements, no solutions.

**Feature:** split-agent-graph
**One-liner:** Split the 463-line agent/graph.py god module into per-node files under agent/nodes/ and keep graph.py as a thin builder.
**Date:** 2026-04-22

## Existing surface area

- `src/commandclaw/agent/graph.py` (463 lines) — the entire subject: state types, 4 node functions, 1 routing function, `run_agent` closure, LLM+tool assembly in `build_agent_graph`, and `TracedGraph` wrapper. Single public import point for all of these.
- `src/commandclaw/agent/__init__.py` — re-exports `AgentResult`, `create_agent`, `invoke_agent`, `invoke_with_retry` from `runtime.py`; does **not** re-export anything from `graph.py`.
- `src/commandclaw/agent/runtime.py` (237 lines) — legacy `AgentExecutor`-based path (`create_agent` + `invoke_agent`). Uses `commandclaw.vault.identity.load_identity` (vault module), not the graph node. Does not import from `graph.py`.
- `src/commandclaw/__main__.py` — sole caller of `build_agent_graph` (L133, L138), inside `_chat_loop`. Import is local (inside the function body).
- `src/commandclaw/agent/tools/` — 9 leaf tool files + `__init__.py`; the prior-art subpackage pattern (see below).
- `tests/test_vault_config_identity.py` — imports `commandclaw.vault.identity.load_identity` (the vault helper), NOT the graph node of the same name. No test in the suite imports any symbol from `commandclaw.agent.graph`.

### Symbols defined in graph.py and their locations

| Symbol | Kind | Lines |
|---|---|---|
| `CommandClawState` | `TypedDict` | L37–48 |
| `CommandClawContext` | `@dataclass` | L51–58 |
| `load_identity` | async node fn | L66–98 |
| `input_guardrails` | async node fn | L101–138 |
| `output_guardrails` | async node fn | L141–180 |
| `route_guardrail_result` | sync routing fn | L183–187 |
| `block_and_notify` | async node fn | L190–199 |
| `build_agent_graph` | builder fn | L207–395 |
| `run_agent` | async closure (inside builder) | L307–357 |
| `TracedGraph` | wrapper class | L398–463 |

### Cross-file imports inside graph.py (deferred, inside functions)

- `commandclaw.guardrails.engine.check_input` / `check_output` — imported inside `input_guardrails` and `output_guardrails`
- `langfuse.get_client` — imported inside both guardrail nodes and `TracedGraph.ainvoke`
- All tool `create_*` functions from `commandclaw.agent.tools.*` — imported inside `build_agent_graph`
- `commandclaw.mcp.client.MCPClient`, `commandclaw.mcp.tools.create_mcp_tools` — imported inside `build_agent_graph`
- `commandclaw.tracing.langfuse_tracing.create_langfuse_handler` — imported inside `build_agent_graph`
- `commandclaw.vault.git_ops.VaultRepo` — imported inside `build_agent_graph`

## Relevant patterns already in the codebase

**tools/ subpackage as prior art:** `src/commandclaw/agent/tools/` splits leaf implementations into per-responsibility files (e.g. `bash_tool.py` 46 lines, `file_read.py` 58 lines, `vault_memory.py` 64 lines) and aggregates a curated public surface in `__init__.py`. Each file exports a single `create_*` factory function. The `__init__.py` lists a stable `__all__`. This is exactly the structural pattern the `nodes/` split would mirror.

**Deferred imports as the existing isolation idiom:** All cross-cutting imports in `graph.py` (guardrails, Langfuse, tools, MCP, vault) are already deferred inside the functions that use them. This means moving a node to its own file requires only hoisting its deferred imports to module-level in that new file; no circular-import surgery is expected.

**`@dataclass` + `TypedDict` co-location:** `CommandClawContext` is a `@dataclass` and `CommandClawState` is a `TypedDict`; both are currently defined at the top of `graph.py` and are used both by the nodes and by `build_agent_graph`. Any split needs a stable home for these types that all new node files can import without circularity.

## Constraints discovered

- **Single external caller of `build_agent_graph`:** only `src/commandclaw/__main__.py` (`_chat_loop`, L133). Import is local (inside the function body), so the public module path `commandclaw.agent.graph.build_agent_graph` must remain stable or `__main__.py` must be updated in the same change.
- **`TracedGraph` is not imported elsewhere:** used only as the return value of `build_agent_graph`. Callers receive it opaquely via the return value; its class path is not referenced externally.
- **No tests cover `graph.py` symbols directly.** The grep for `build_agent_graph`, `TracedGraph`, `CommandClawState`, and all 4 node function names across `tests/` returns only `test_vault_config_identity.py`, which imports the unrelated `commandclaw.vault.identity.load_identity`. The graph is effectively untested at the unit level.
- **`run_agent` is a closure** — it captures `inner_agent`, `_mcp_client`, `_mcp_loaded`, `_mcp_lock`, `langfuse_handler`, and `llm` from `build_agent_graph`'s local scope via `nonlocal`. It cannot be extracted as a plain module-level function without converting those captures to arguments or a context object.
- **Name collision risk:** `load_identity` exists both as a graph node (in `graph.py`) and as a vault utility function (`commandclaw.vault.identity.load_identity`). The graph node reads `IDENTITY.md`, `AGENTS.md`, and `USER.md` directly from the vault path; the vault utility returns a parsed `VaultIdentity` object. These are functionally related but structurally distinct. Any per-node file for this node will need a name that does not shadow the vault helper when both are in scope.
- **Ruff rules in force:** `E,F,I,N,W,UP`, `line-length=100`, `target-version=py311`. Any new `nodes/` files must pass ruff. Import ordering (`I`) will require careful `__future__` annotation + stdlib / third-party / local grouping in each new file.
- **`asyncio_mode = "auto"` + strict markers:** any new tests written against extracted nodes must use `async def test_*` directly and register markers before use.

## qmd findings (if enabled)

Query executed against `shikhar-wiki` with both a lexical sub-query (`LangGraph StateGraph nodes module`) and a vector sub-query (`splitting a god module into smaller files deep module philosophy`), intent `refactor god module into per-node files`.

Top result (`shikhar-wiki/concepts/agentic-coding.md`, score 0.88) covers agentic coding workflows generally; it does not discuss LangGraph node decomposition or module-splitting philosophy in a way relevant to this refactor. All other results scored 0.5 or below and are off-topic (software factory patterns, AI adoption levels, wiki index, etc.).

**No clearly relevant hits.** The wiki does not contain material on LangGraph internal architecture or deep-module vs. shallow-module philosophy.

## Unknowns surfaced

- Whether `CommandClawState` and `CommandClawContext` should live in a new `nodes/state.py` (or `agent/state.py`) vs. staying in a trimmed `graph.py` — neither option is forced by the current codebase.
- How to handle `run_agent` given its closure captures: options include converting captures to constructor arguments on a class, passing them as parameters, or keeping `run_agent` defined inside `build_agent_graph` in `graph.py` while the four standalone nodes move out. The codebase provides no precedent for closure-carrying nodes.
- Whether `TracedGraph` belongs in `nodes/` or in a separate `tracing/` layer — `commandclaw.tracing.langfuse_tracing` already exists as a sibling module, which could be relevant.
- `agent/__init__.py` currently exports only `runtime.py` symbols; it is silent about `graph.py`. Whether the refactor should surface graph symbols through `agent/__init__.py` is not determined by any existing convention.
- No unit tests exist for any node function. Whether the refactor is expected to introduce tests (TDD green/refactor pass) is not specified by the current file structure.
