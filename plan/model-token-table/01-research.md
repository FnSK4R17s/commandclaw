# Stage 1 — Research

> Observation only. No design, no requirements, no solutions.

**Feature:** model-token-table
**One-liner:** Lift the model to max_tokens lookup from inline in agent/graph.py into a config/models registry so the mapping is not buried in the graph builder.
**Date:** 2026-04-22

## Existing surface area

Files this feature will directly touch or depend on.

- `src/commandclaw/agent/graph.py` — `build_agent_graph`: contains the inline if/elif model-name substring check (lines 217–232); the only place where `max_tokens` is computed and passed to `ChatOpenAI`.
- `src/commandclaw/config.py` — `Settings` dataclass (pydantic-settings, env prefix `COMMANDCLAW_`): holds `openai_model`, `openai_api_key`, `openai_base_url`, `openai_temperature`. No token-related field exists.
- `src/commandclaw/agent/runtime.py` — legacy `create_agent` used by the Telegram path: instantiates `ChatOpenAI` at lines 94–102 **without** `max_tokens`. The omission is silent — LangChain will send no `max_tokens` param and rely on the API default.
- `src/commandclaw/__main__.py` — no LLM instantiation; delegates to `build_agent_graph` (chat/bootstrap) or `create_agent` (telegram). No model-name strings referenced.
- `pyproject.toml` — no model list, no token constants; `langchain-openai>=1.1` is the relevant dep.
- `tests/` — zero test files reference model names, `max_tokens`, or `openai_model`.

## Exact inline block (graph.py lines 217–226)

```python
    # --- LLM ---
    # Model-specific max output tokens — don't exceed model limits
    model_name = settings.openai_model or ""
    if "5.4-mini" in model_name or "gpt-5" in model_name:
        max_tokens = 128_000
    elif "4.1-mini" in model_name or "4o-mini" in model_name:
        max_tokens = 32_000
    elif "o1" in model_name or "o3" in model_name or "o4" in model_name:
        max_tokens = 100_000
    else:
        max_tokens = 16_384  # Safe default
```

## Complete map of every hard-coded model-name string in the codebase

| File | Line(s) | String(s) | Purpose |
|------|---------|-----------|---------|
| `src/commandclaw/config.py` | 45 | `"gpt-5.4-mini"` | Default value for `openai_model` field |
| `src/commandclaw/agent/graph.py` | 219 | `"5.4-mini"`, `"gpt-5"` | Substring check — maps to 128 000 token limit |
| `src/commandclaw/agent/graph.py` | 221 | `"4.1-mini"`, `"4o-mini"` | Substring check — maps to 32 000 token limit |
| `src/commandclaw/agent/graph.py` | 223 | `"o1"`, `"o3"`, `"o4"` | Substring check — maps to 100 000 token limit |

No other Python file contains hard-coded model-name strings. `pyproject.toml` has none. Tests have none.

## Complete map of every `max_tokens` occurrence

| File | Lines | Role |
|------|-------|------|
| `src/commandclaw/agent/graph.py` | 220, 222, 224, 226 | Assignment targets inside the if/elif/else ladder |
| `src/commandclaw/agent/graph.py` | 232 | Key in `llm_kwargs` dict passed to `ChatOpenAI` |
| `src/commandclaw/agent/runtime.py` | — | **Absent.** `llm_kwargs` at lines 95–101 does not include `max_tokens`. `ChatOpenAI` is constructed with only `api_key`, `model`, `temperature`, and optionally `base_url`. |

## Relevant patterns already in the codebase

- **`Settings` as the single source of truth for config** (`src/commandclaw/config.py`). Every runtime value that varies between deployments lives there. The existing pattern is to add a `Field(default=..., description=...)` and read it from `settings.*` downstream.
- **Lazy imports inside functions** (`runtime.py` lines 31–49). LangChain / LangGraph imports are deferred to the function body, not at module top-level. Any new module following this pattern should do the same where import cost matters.
- **`llm_kwargs: dict[str, Any]` assembly pattern** (both `graph.py:228–235` and `runtime.py:95–101`). Both sites build a dict and splat it into `ChatOpenAI(...)`. A registry lookup would slot naturally into this pattern as an additional key.

## Constraints discovered

- Python >= 3.11; `target-version = "py311"` in ruff. Type annotations can use `X | Y`, `dict[str, Any]`, etc.
- Ruff rules `E, F, I, N, W, UP` at line-length 100. Any new module must pass `ruff check`.
- `pydantic-settings >= 2`. `Settings` uses `BaseSettings`; field defaults must be JSON-serialisable or use `Field(default_factory=...)`.
- `pytest-asyncio` with `asyncio_mode = "auto"`. Tests must be `async def test_*` without decorator. Markers must be pre-registered.
- No existing test exercises the max_tokens lookup path. Coverage will need to be created from scratch.
- `runtime.py` is the Telegram code path. It omits `max_tokens` entirely today. Any refactor that touches the registry will surface the question of whether to also fix the Telegram path — that is an open question, not a constraint.

## qmd findings

Both searches (lex `"model capability lookup table"` and vec `"moving configuration constants out of business logic into a registry"`) against `shikhar-wiki` returned no relevant hits. Top results were graph-theory articles and software-factory concept pages, none of which relate to this feature. No qmd citations to include.

## Unknowns surfaced

1. **Where does the new registry live?** Candidates: a new `src/commandclaw/models.py` module, a new field/nested model inside `Settings`, a YAML/JSON data file read at import time, or an inline `dict` constant in `config.py`. The codebase has no prior art for a standalone constants registry.
2. **Should `runtime.py` (Telegram path) also adopt the registry?** It currently passes no `max_tokens` at all. The refactor could fix both paths or leave the Telegram path for a follow-on.
3. **Substring matching vs. exact matching.** The current `"o1" in model_name` check would false-positive on a hypothetical `"gpt-o1-preview"` or any model name containing `"o1"` as a substring. A registry keyed on exact strings or prefix patterns would need a deliberate matching strategy.
4. **Who owns the token values?** They are not documented against any OpenAI API spec in the repo. The numbers (128 000, 32 000, 100 000, 16 384) appear to be hand-entered. There is no link to an external source of truth.
5. **Is `max_tokens` the only per-model constant?** For now yes, but reasoning models (`o1`, `o3`, `o4`) may require other flags (`temperature=1`, `reasoning_effort`, etc.) in future. The design question of whether the registry should be token-only or capability-general is out of scope for research but is a known dependency.
