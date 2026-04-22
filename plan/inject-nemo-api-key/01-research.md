# Stage 1 — Research

> Observation only. No design, no requirements, no solutions.

**Feature:** inject-nemo-api-key
**One-liner:** Inject the OpenAI API key into CommandClawState so NeMo guardrails in agent/graph.py stop running with a null key.
**Date:** 2026-04-22

## Existing surface area

### State type — `CommandClawState`

`src/commandclaw/agent/graph.py` L37–48: `CommandClawState` TypedDict declares eight fields:
`messages`, `session_type`, `trigger_source`, `user_id`, `agent_id`, `memory_loaded`,
`vault_context`, `guardrail_violations`, `identity_prompt`.

`_api_key` is **not declared**. It is accessed via `state.get("_api_key")` — the undeclared
key pattern that `_vault_path` also uses (L68). LangGraph does not reject undeclared
TypedDict keys at runtime; they are simply absent from the checkpointed state schema.

### Guardrail nodes that read `_api_key`

- `input_guardrails` (L101–138): L114 `api_key = state.get("_api_key")`. Passes it to
  `check_input(content, api_key=api_key)` at L126 (inside Langfuse span) and L133
  (exception fallback path). Both call sites receive `None` in every current invocation.

- `output_guardrails` (L141–180): L156 `api_key = state.get("_api_key")`. Passes it to
  `check_output(content, api_key=api_key)` at L168 (inside Langfuse span) and L175
  (exception fallback path). Same: always `None`.

### `TracedGraph.ainvoke` — input dict never writes `_api_key`

`TracedGraph.ainvoke` (L408–463) is a thin wrapper. It reads `input_.get("agent_id")` and
`input_.get("messages")` for tracing metadata (L410–415), then delegates to
`self._graph.ainvoke(input_, config=config, **kwargs)` at L434. It does not inspect,
transform, or inject any key-related field. The raw `input_` dict from the caller flows
through unchanged.

### Call site — `__main__._chat_loop`

`src/commandclaw/__main__.py` L190–204: the only call site for the graph in the entire
codebase. It constructs the input dict as:

```
{
    "messages": [HumanMessage(content=message)],
    "session_type": "general",
    "trigger_source": "user",
    "user_id": "cli",
    "agent_id": settings.agent_id or "default",
    "memory_loaded": False,
    "vault_context": [],
    "guardrail_violations": [],
    "identity_prompt": "",
    "_vault_path": str(settings.vault_path),
}
```

`_api_key` is absent. `settings.openai_api_key` is available in scope (the `settings`
object is passed to `_chat_loop`) but is never threaded into this dict.

### The env-var bridge that partially masks the bug

`src/commandclaw/__main__.py` L38–39 (inside `main()`, before `_chat_loop` is called):

```python
# NeMo Guardrails uses langchain's OpenAI which reads OPENAI_API_KEY
os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
```

This line runs unconditionally for `chat` and `bootstrap` modes before the graph is
ever built. By the time `_init_nemo(api_key=None)` is called inside the guardrail
nodes, `OPENAI_API_KEY` is already set in the process environment.

### `engine._init_nemo` — env-var fallback path

`src/commandclaw/guardrails/engine.py` L27–69:

```
_init_nemo(api_key: str | None = None)
```

Decision tree at L44–51:
1. If `api_key` is truthy → `os.environ["OPENAI_API_KEY"] = api_key` (overwrites).
2. Else if `OPENAI_API_KEY` already in `os.environ` → do nothing (key present, NeMo
   will find it).
3. Else → try `COMMANDCLAW_OPENAI_API_KEY`; if non-empty, write to `OPENAI_API_KEY`.

`_rails_initialized` is a module-level boolean (L19). Once `_init_nemo` returns (success
or failure), every subsequent call is a no-op regardless of the `api_key` argument. This
means the first call wins: if the env var was already set by `__main__.py` L39, NeMo
initialises successfully on that first call and all subsequent calls skip the key logic
entirely.

### `check_input` and `check_output` call paths

- `check_input` (L104–131): calls `_init_nemo(api_key)` at L112. If NeMo initialised, runs
  `_rails.generate_async(...)` at L114. Falls back to regex jailbreak patterns at L126–129.
  Returns `list[str]` of violations.

- `check_output` (L134–166): always runs regex secret patterns (L142–149) and PII patterns
  (L146–149) unconditionally first. Calls `_init_nemo(api_key)` at L152 only if no regex
  violations yet. Returns `list[str]` of violations.

### `Settings.openai_api_key`

`src/commandclaw/config.py` L40–43:

```python
openai_api_key: str = Field(
    default="",
    description="OpenAI API key (or Codex OAuth access token).",
)
```

Sourced from env var `COMMANDCLAW_OPENAI_API_KEY` (prefix `COMMANDCLAW_` applied by
`SettingsConfigDict` at L14–18) or from `.env` file. Validated as non-empty at
`__main__.py` L34–36 — the process exits if absent.

### Tests

Zero test files touch guardrail paths. `find /apps/commandclaw/tests/ -name "*.py" | xargs grep -l "guardrail\|check_input\|check_output\|nemo\|_api_key"` returns no matches. The test suite covers: `test_agent_retry.py`, `test_tools_bash.py`, `test_tools_files.py`, `test_vault_config_identity.py`, `test_vault_git_ops.py`, `test_vault_memory.py`, `test_vault_skills.py`. No test would have caught this bug.

### Full `_api_key` footprint

Every occurrence in the codebase:

| File | Line | Role |
|------|------|------|
| `src/commandclaw/agent/graph.py` | 114 | `state.get("_api_key")` in `input_guardrails` |
| `src/commandclaw/agent/graph.py` | 156 | `state.get("_api_key")` in `output_guardrails` |

That is the complete footprint. No writer, no injector, no test.

### Full `OPENAI_API_KEY` / `COMMANDCLAW_OPENAI_API_KEY` footprint

| File | Line | Role |
|------|------|------|
| `src/commandclaw/__main__.py` | 35 | Error log text references `COMMANDCLAW_OPENAI_API_KEY` |
| `src/commandclaw/__main__.py` | 39 | `os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)` — the env bridge |
| `src/commandclaw/guardrails/engine.py` | 44–51 | `_init_nemo` env fallback logic |

## Relevant patterns already in the codebase

**`_vault_path` precedent** (`graph.py` L68): `load_identity` reads
`state.get("_vault_path", "/workspace")` — the same out-of-band undeclared key pattern
used for `_api_key`. The call site in `__main__.py` L201 passes `"_vault_path"` in the
input dict. This is the established pattern for injecting runtime context that is not
part of the typed state schema.

**`settings.openai_api_key` already used at graph build time** (`graph.py` L229):
`llm_kwargs["api_key"] = settings.openai_api_key` when constructing the `ChatOpenAI`
instance. The key is already flowing through `settings` to the graph builder; it simply
never reaches the state dict.

**`os.environ.setdefault` bridge** (`__main__.py` L39): deliberate workaround comment
`# NeMo Guardrails uses langchain's OpenAI which reads OPENAI_API_KEY`. This was an
explicit decision to set the env var once at startup rather than plumb the key through
state — but it only works because `main()` is the entry point. Any future caller that
uses `build_agent_graph` directly (e.g., a test harness, a non-CLI invoker) would not
benefit from this bridge.

**`asyncio_mode = "auto"`** (`pyproject.toml`): async tests need no decorator — write
`async def test_*` directly.

## Constraints discovered

- **`_rails_initialized` is a process-global singleton** (`engine.py` L19, L31–33). Once
  NeMo initialises (or fails to initialise), `_init_nemo` is a no-op for the rest of the
  process. Injecting `_api_key` into state would only matter on the very first call to
  `_init_nemo`. If the env var bridge in `__main__.py` L39 already ran before the first
  guardrail node executes, `_api_key` is effectively irrelevant in production.

- **The bug is severity-downgraded by `__main__.py` L39** in the CLI path. For any
  invocation via `commandclaw chat` or `commandclaw bootstrap`, `OPENAI_API_KEY` is set
  before `_chat_loop` runs. NeMo initialises successfully via the env fallback even
  though `_api_key=None`. This is a masked bug: NeMo is silently working via the env var,
  not via the state field. The state field is dead code.

- **The bug has real severity in non-CLI paths**: any caller that imports
  `build_agent_graph` directly — tests, Docker entrypoints, future API servers — bypasses
  the `main()` env bridge entirely. In those contexts, `OPENAI_API_KEY` may be absent,
  `_api_key=None`, and NeMo will fail to initialise, silently degrading to regex-only
  guardrails.

- **`CommandClawState` TypedDict** does not declare `_api_key`. Adding it as an
  undeclared extra key (like `_vault_path`) is currently possible but bypasses type
  checking. Declaring it formally in the TypedDict would require a default value or
  marking it `NotRequired`.

- **Checkpointer serialises state**: `MemorySaver` serialises the full state dict. An
  `_api_key` field in state would be persisted to the checkpointer on every turn. API
  keys in checkpointed memory is a potential secret-leakage vector.

- **Ruff rules**: `target-version = "py311"`, `line-length = 100`, rules `E,F,I,N,W,UP`.
  Run `./.venv/bin/ruff check .` before commit.

- **Async tests**: `asyncio_mode = "auto"`, strict markers, `./.venv/bin/pytest`.

## qmd findings (if enabled)

Searches run on `shikhar-wiki` and `shikhar-raw` with:
- `{type: 'lex', query: 'LangGraph state dependency injection'}`
- `{type: 'vec', query: 'passing API keys through a graph state object'}`
- `intent: 'inject API key into LangGraph runtime state'`

No relevant hits. Top result in both collections (`shikhar-wiki/concepts/directed-graph.md`
score 0.88, `shikhar-raw/external-memory-graph-traversal.md` score 0.88) is generic graph
theory — not applicable. Nothing in the personal wiki addresses LangGraph state injection
or API key plumbing patterns.

## Unknowns surfaced

- **Was `_api_key` ever intentionally injected somewhere that has since been deleted?**
  There is no git evidence in scope. The field appears to be an unfinished implementation
  placeholder — the intent was clear (inject via state), the wiring was never completed.

- **Is `OPENAI_API_KEY` reliably set in Docker/production before the graph runs?**
  `scripts/spawn-agent.sh` is mentioned in CLAUDE.md as the Docker entrypoint but was not
  in scope. If that script sources env vars before calling `commandclaw chat`, the env
  bridge in `__main__.py` L39 fires and NeMo works. If it calls `build_agent_graph`
  directly or uses a different entry path, the bridge does not fire.

- **Does `_rails_initialized = True` get set even on `ImportError` / `Exception`?**
  Yes: L34 sets `_rails_initialized = True` before the try block at L36. A failure
  (NeMo not installed, config missing) silently locks NeMo out for the rest of the
  process with no retry path. This is a separate robustness concern but interacts with
  the key injection question — if NeMo initialises on first call with env key, a later
  attempt to inject via state cannot re-init.

- **Should `_api_key` be stored in checkpointed state at all?** If `_api_key` is added
  to `CommandClawState` and the input dict, it will be serialised by `MemorySaver` on
  every turn. This may be intentional (the key is needed on every turn), but it also
  means API keys are persisted to in-memory checkpoint storage. For disk-backed
  checkpointers this would be a security concern.

- **Is there a test that exercises the guardrail nodes end-to-end with a real or mocked
  NeMo init?** No. Zero test coverage for the entire guardrail path. Any fix is untested
  until tests are added.

- **What is the right injection point if `_vault_path` is the model?** The `_vault_path`
  pattern requires the caller to know and pass the path. The analogous pattern for
  `_api_key` would require the caller to pass `settings.openai_api_key` explicitly in
  the input dict. Alternatively, `build_agent_graph` could capture the key at build time
  (it already has `settings`) and inject it in a wrapper node before `input_guardrails`.
  Neither approach is evaluated here.
