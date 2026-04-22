# Stage 1 — Research

> Observation only. No design, no requirements, no solutions.

**Feature:** runtime-max-tokens-default
**One-liner:** Apply a model-appropriate max_tokens in agent/runtime.py's ChatOpenAI so the Telegram agent path doesn't silently rely on the API default.
**Date:** 2026-04-22

## Existing surface area

Files this feature will directly touch or depend on.

- `src/commandclaw/agent/runtime.py` — `create_agent`: constructs `ChatOpenAI` at lines 94–102 **without** `max_tokens`. The four kwargs passed are: `api_key`, `model`, `temperature`, and conditionally `base_url`. No token limit of any kind is set.
- `src/commandclaw/agent/graph.py` — `build_agent_graph`: constructs `ChatOpenAI` at lines 228–236 **with** `max_tokens` set via the inline if/elif/else ladder at lines 218–226. This is the only place in the repo where `max_tokens` is computed and passed to the LLM.
- `src/commandclaw/config.py` — `Settings` dataclass (pydantic-settings, env prefix `COMMANDCLAW_`). LLM fields: `openai_api_key`, `openai_model` (default `"gpt-5.4-mini"`), `openai_temperature` (default `0.2`), `openai_base_url` (optional). **No `max_tokens` field exists.** `telegram_chunk_size` (default `4000`) is a separate Telegram-level setting.
- `src/commandclaw/telegram/bot.py` — `start_bot`: thin wrapper; passes `agent_executor` from `create_agent` into handler registration. No token logic.
- `src/commandclaw/telegram/handlers.py` — `create_message_handler`: calls `invoke_with_retry(agent_executor, text, settings, session_id=str(chat_id), user_id=str(chat_id))`. Receives `AgentResult`. If `result.success`, calls `send_message(..., chunk_size=settings.telegram_chunk_size)`.
- `src/commandclaw/telegram/sender.py` — `send_message`: chunks `result.output` into segments of at most `telegram_chunk_size` characters (default 4000) before sending to Telegram. Prefers splitting at newlines. **Chunking is purely cosmetic** — it divides whatever text the agent already produced; it does not cap the LLM's output before generation. No interaction with `max_tokens`.
- `src/commandclaw/agent/tools/bash_tool.py` — defines `MAX_OUTPUT_LENGTH = 50_000` (characters). Tool output fed back into the LLM context is hard-capped at 50 000 chars per invocation. **Orthogonal** to `max_tokens` — this limits tool input to the LLM, not LLM output.
- `pyproject.toml` — `langchain-openai>=1.1` (line 16). No upper bound pinned.
- `tests/` — zero test files reference `max_tokens`, `openai_model`, or response-length constraints on the LLM layer.

## Exact LLM construction block in runtime.py (lines 94–102)

```python
    # --- LLM ---
    llm_kwargs: dict[str, Any] = {
        "api_key": settings.openai_api_key,
        "model": settings.openai_model,
        "temperature": settings.openai_temperature,
    }
    if settings.openai_base_url:
        llm_kwargs["base_url"] = settings.openai_base_url
    llm = ChatOpenAI(**llm_kwargs)
```

`max_tokens` is absent. `ChatOpenAI` is constructed with only three or four keys.

## Exact max_tokens logic in graph.py (lines 217–232)

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

    llm_kwargs: dict[str, Any] = {
        ...
        "max_tokens": max_tokens,
    }
```

Four branches: gpt-5 family (128 000), 4.1-mini/4o-mini (32 000), o1/o3/o4 reasoning models (100 000), else/fallback (16 384).

## Is the current behavior actually broken, or just fragile?

**Assessment: fragile, not currently broken — but the fragility is real and escalates with model upgrades.**

Evidence gathered:

1. **No error logs or bug reports in DEVLOG.** Neither `guiding_docs/DEVLOG.md` nor the devlog entries (`2026-04-06.md`, `2026-04-07.md`) mention a truncated-response complaint or an OpenAI error from the Telegram path. There is no evidence of observed failures today.

2. **The gap is explicitly noted in prior research.** The `model-token-table` research (`plan/model-token-table/01-research.md`, line 15) and the `unify-agent-entry` research (`plan/unify-agent-entry/01-research.md`, line 47) both record the omission as a known asymmetry, not as a runtime failure.

3. **Why it has not broken yet.** When `max_tokens` is omitted from a `ChatOpenAI` call with `langchain-openai>=1.1`, LangChain sends no `max_tokens` field in the API request. The OpenAI API then applies its own default: for recent models (GPT-4o, GPT-4.1, GPT-5) the effective default is `max_completion_tokens=None` — the model generates until it reaches a natural stop token or the context window ceiling. For typical chat and short-task messages (the primary Telegram use case), the model stops well before the ceiling, so no truncation occurs. The API default is generous, not zero.

4. **Where it becomes a real risk.** The risk materializes in three concrete scenarios:
   - **Long-form agent tasks over Telegram.** If a Telegram user asks for a multi-file code refactor, a detailed plan, or comprehensive analysis, the model may produce a response approaching its context ceiling. Without a cap, API cost and latency are unbounded. The chunking in `sender.py` will transmit whatever comes back, but it does not limit generation.
   - **Model upgrade changes the API default.** The default `max_tokens` behaviour for a given model is not guaranteed stable across OpenAI API versions. If OpenAI adjusts it, the Telegram path silently changes behaviour without any config change in CommandClaw.
   - **Reasoning models (`o1`, `o3`, `o4`).** If `settings.openai_model` is set to a reasoning model for a Telegram-deployed agent, the absence of `max_tokens` is materially worse: reasoning models produce long internal chain-of-thought tokens that count against the context window. The graph path explicitly caps these at 100 000. The runtime path provides no cap at all, so a reasoning model on the Telegram path could burn through token budgets silently.

5. **`telegram_chunk_size = 4000` does NOT protect against LLM over-generation.** It is a presentation-layer split applied after generation completes. It cannot prevent the model from generating 200 000 tokens.

6. **`MAX_OUTPUT_LENGTH = 50 000` in bash_tool.py is orthogonal.** It caps tool-call stdout fed back into context, not the LLM's own generated tokens.

## Overlap with model-token-table

The `model-token-table` feature (`plan/model-token-table/`) is the parent of this bug. Its scope is lifting the inline if/elif/else table from `graph.py` into a registry. This bug is a narrower symptom: `runtime.py` has no `max_tokens` at all, not even a hardcoded constant.

The two features share their fix. A registry introduced by `model-token-table` would be the natural home for the lookup that `runtime.py` currently does not perform. Correct sequencing:

- If `model-token-table` is implemented first, this bug becomes a one-line change: add the registry call to `runtime.py`'s `llm_kwargs`.
- If this bug is fixed as a standalone, it must not duplicate the `graph.py` inline logic again — that would create a third copy of the table. Instead it should either (a) extract the existing `graph.py` logic into a shared helper (which is the first step of implementing `model-token-table` anyway), or (b) import and call whatever registry `model-token-table` introduces.

There is a third overlap: `unify-agent-entry` — if that feature proceeds first and collapses `runtime.py` into `graph.py`, this bug disappears automatically since `graph.py` already sets `max_tokens`. Stage 2 should decide whether to merge, sequence, or track the three features independently.

## Relevant patterns already in the codebase

- **`llm_kwargs` dict-splatting pattern.** Both `graph.py` (lines 228–235) and `runtime.py` (lines 95–101) build a `dict[str, Any]` and splat into `ChatOpenAI(...)`. Adding `max_tokens` to `runtime.py` follows the same pattern: add one key to `llm_kwargs`.
- **`Settings` as the single config source.** Every deployment-variable comes from `settings.*`. A `max_tokens` value derived from the model name fits this pattern as a computed/derived value, not a raw env var.
- **Conditional key injection.** `openai_base_url` is injected conditionally in `runtime.py` (`if settings.openai_base_url: llm_kwargs["base_url"] = ...`). This is precedent for adding keys to `llm_kwargs` conditionally; `max_tokens` would be unconditional (always present, based on model name).
- **`__main__.py` deferral comment.** Line 63: `# Telegram mode still uses old runtime for now` — explicit acknowledgement of the split as known tech debt.

## Constraints discovered

- Python >= 3.11; `target-version = "py311"` in ruff. Type annotations can use `X | Y`, `dict[str, Any]`.
- Ruff rules `E, F, I, N, W, UP` at line-length 100. Any new code must pass `./.venv/bin/ruff check .`.
- `langchain-openai>=1.1` — no upper bound. Default `max_tokens=None` behaviour is version-sensitive and not guaranteed stable.
- `pydantic-settings >= 2`. Adding a `max_tokens` field to `Settings` is possible but introduces a new env var (`COMMANDCLAW_MAX_TOKENS`). Whether that is desired vs. a purely computed value is a Stage 2 question.
- `pytest-asyncio` with `asyncio_mode = "auto"`. No `@pytest.mark.asyncio` needed. Markers must be pre-registered in `pyproject.toml`.
- No existing test covers the `max_tokens` code path in either `graph.py` or `runtime.py`. Any change requires new test coverage from scratch.
- The `ChatOpenAI` constructor in `runtime.py` is inside an `async` function behind a lazy import — any shared helper must be importable from that context.
- The `graph.py` substring matching (`"o1" in model_name`) could false-positive on a model string like `"gpt-o1-preview"`. Any shared helper carries this same caveat and should document it.

## qmd findings

Both searches (`{type: 'lex', query: 'max_tokens default langchain openai'}` and `{type: 'vec', query: 'model output token limit API default behavior'}`) against `shikhar-wiki` returned no relevant hits. No qmd citations to include.

## Unknowns surfaced

1. **What is the exact OpenAI API default for `max_tokens` when omitted?** Documentation as of August 2025 describes `max_completion_tokens` as optional; when omitted the model generates until a stop token or context-window ceiling. For GPT-4o and GPT-4.1 the context window is 128 000 tokens. No DEVLOG evidence of truncation observed on the Telegram path, but risk is real for long tasks and reasoning models.
2. **Should `max_tokens` be a `Settings` field or purely a derived/computed value?** A `Settings` field allows per-deployment override. A derived value requires a registry lookup per model name. These options are not mutually exclusive (Settings override + registry default), but the shape is a Stage 2 design question.
3. **Should this feature be merged into the `model-token-table` backlog item?** The overlap is near-total. A standalone fix that adds a hardcoded fallback to `runtime.py` solves the immediate gap but creates a third copy of the model-to-token mapping. Stage 2 should resolve ordering or merging before producing requirements.
4. **Does the fix apply before or after `unify-agent-entry`?** If `unify-agent-entry` proceeds first and collapses `runtime.py` into `graph.py`, the bug disappears automatically. If this fix is applied to `runtime.py` independently first, it may be thrown away by the later unification. The triple-overlap of `runtime-max-tokens-default`, `model-token-table`, and `unify-agent-entry` should be resolved in Stage 2.
5. **Is there any operational evidence of actual truncation?** DEVLOG shows no such reports for the Telegram path as of 2026-04-07 (the last entry). The bug is latent, not active.
6. **Reasoning model risk on the Telegram path.** If `COMMANDCLAW_OPENAI_MODEL` is ever set to an `o1`/`o3`/`o4` model for a Telegram-deployed agent, the absence of `max_tokens` is qualitatively worse than for standard chat models, because reasoning tokens are long and expensive. This is a higher-severity variant of the same bug.
