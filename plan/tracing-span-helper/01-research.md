# Stage 1 — Research

> Observation only. No design, no requirements, no solutions.

**Feature:** tracing-span-helper
**One-liner:** Factor the duplicated Langfuse start_as_current_observation boilerplate from agent/graph.py into a context manager in the tracing/ package.
**Date:** 2026-04-22

---

## Existing surface area

Files this feature will touch or depend on:

- `src/commandclaw/tracing/langfuse_tracing.py` — Langfuse singleton init, `create_langfuse_handler`, `flush_tracing`. The span helper would live here or in a sibling file.
- `src/commandclaw/tracing/__init__.py` — currently a single docstring line, no exports. Would need updating to re-export the new helper.
- `src/commandclaw/agent/graph.py` — three `start_as_current_observation` call sites (Sites A, B, C below).
- `src/commandclaw/agent/runtime.py` — one `start_as_current_observation` call site (Site D below).
- `src/commandclaw/config.py:78-81` — `Settings` fields `langfuse_public_key`, `langfuse_secret_key`, `langfuse_host`. Not changed by this feature but referenced by the tracing module.
- `src/commandclaw/__main__.py:134,141,143` — calls `flush_tracing()` and `propagate_attributes` on shutdown. Not a call site for spans; no change expected.

No tests currently cover Langfuse trace shape or mock `start_as_current_observation`.

---

## Relevant patterns already in the codebase

**Singleton guard pattern** (`langfuse_tracing.py:16-44`): `_ensure_langfuse` initialises once and swallows `ImportError` + general exceptions, returning `bool`. All callers tolerate `None` / disabled tracing gracefully. Any new helper must follow the same defensive pattern.

**`try/except`-wrapped import at call site** (graph.py:118, 160, 420; runtime.py:185): Every `start_as_current_observation` block is guarded by a bare `from langfuse import get_client as get_langfuse` inside a `try/except Exception`. This means callers already expect the tracing path to silently no-op when Langfuse is absent.

**Manual `__enter__`/`__exit__` for async boundaries** (Sites C and D): When the traced work is `await`-ed, the codebase does not use `with` — it calls `__enter__` before the `await` and `__exit__` after. This is because `start_as_current_observation` returns a synchronous context manager even in v4.

**`span.update()` called inside the block** (Sites A, B): Guardrail spans call `span.update(output=..., level=...)` while still inside the `with` block, before `__exit__`. The helper must preserve this ability (i.e., yield the span object).

**`lf.set_current_trace_io` + `lf.update_current_span`** (Site C only): The `TracedGraph.ainvoke` path sets trace-level I/O after the main invocation, using client-level helpers rather than the span object. This is distinct from the `span.update()` pattern in Sites A/B/D.

---

## Constraints discovered

- **Langfuse SDK:** `langfuse>=4` (no upper bound). All observed API surface (`get_client`, `start_as_current_observation`, `propagate_attributes`, `set_current_trace_io`, `update_current_span`) is v4-only.
- **Python ≥ 3.11.** `contextlib.asynccontextmanager` and `contextlib.contextmanager` both available.
- **Ruff:** `E, F, I, N, W, UP`, line-length 100, `target-version = "py311"`. No `PLW0603` (`global`) except where already suppressed.
- **`asyncio_mode = "auto"`** in pytest; `--strict-markers`. Any new test file must not introduce unregistered markers.
- **Four call sites are not identical** — see shape-diff table in Section 5 below. A single helper cannot mechanically replace all four without either accepting many parameters or being split into two helpers (guardrail vs. span).
- **Site D has an exception-path resource leak:** if `agent_executor.ainvoke` raises, `langfuse_ctx.__exit__` is never called. The current helper does not protect against this; the refactor is an opportunity to fix it.

---

## qmd findings

Both searches against `shikhar-wiki` (lex: `context manager decorator observability span`; vec: `consolidating observability boilerplate into a helper`) returned no relevant hits. Top result (score 0.88) was a generic wiki template file. No prior knowledge in the personal wiki applicable to this feature.

---

## Call-site inventory and shape differences

Four occurrences of `start_as_current_observation` across two files.

### Site A — `graph.py` `input_guardrails` (L121-131)

- Protocol: `with lf.start_as_current_observation(...) as span`
- `as_type="guardrail"`, `name="input_guardrails"` (static)
- `input={"message": content[:500]}` — truncated
- Inside block: `span.update(output={"passed": ..., "violations": ...}, level="WARNING"|"DEFAULT")`
- No `set_current_trace_io`
- Exception handling: outer `try/except Exception` re-runs work without tracing

### Site B — `graph.py` `output_guardrails` (L163-173)

Structurally identical to Site A:
- `name="output_guardrails"` (static), same `as_type="guardrail"`
- Same input truncation, same `span.update` pattern with output + level
- Same fallback behaviour

### Site C — `graph.py` `TracedGraph.ainvoke` (L423-461)

- Protocol: manual `__enter__` before `await`, `__exit__` after
- `as_type="span"`, `name=agent_id` (dynamic)
- `input={"message": user_input[:500]}` for span; full `user_input` for `set_current_trace_io`
- Post-await: `lf.set_current_trace_io(input=..., output=...)` + `lf.update_current_span(output=...)`
- Exception path: `__exit__` called explicitly in the `except` branch before re-raise
- No `metadata` at construction

### Site D — `runtime.py` `invoke_agent` (L189-215)

- Protocol: manual `__enter__` before `await`, `__exit__` after
- `as_type="span"`, `name=agent_name` (dynamic)
- `input={"message": message}` — **not** truncated
- `metadata={"agent_id": agent_name, "session_id": session_id}` — only site that sets construction-time metadata
- Post-await: `langfuse_ctx.update(output=...)` directly on context object (not via `lf.update_current_span`)
- **No `set_current_trace_io`**
- **Exception path: `__exit__` never called if `ainvoke` raises — resource leak**

### Shape-diff summary table

| | Site A (input_guardrails) | Site B (output_guardrails) | Site C (TracedGraph.ainvoke) | Site D (runtime invoke_agent) |
|---|---|---|---|---|
| `as_type` | `"guardrail"` | `"guardrail"` | `"span"` | `"span"` |
| `name` | static | static | dynamic | dynamic |
| `input` truncation | `[:500]` | `[:500]` | `[:500]` (span), full (trace-IO) | none |
| `metadata` at construction | no | no | no | yes |
| context protocol | `with ... as span` | `with ... as span` | manual enter/exit | manual enter/exit |
| `span.update()` inside block | yes (output + level) | yes (output + level) | no | yes (output only) |
| `set_current_trace_io` | no | no | yes | no |
| exception-path close | via `with` (automatic) | via `with` (automatic) | explicit in `except` | missing (leak) |
| fallback (no tracing) | re-runs work in `except` | re-runs work in `except` | work runs unconditionally | work runs unconditionally |

---

## Unknowns surfaced

- Whether the two distinct patterns (guardrail `with`-style vs. span manual-enter/exit) should become one helper with a mode parameter, two separate helpers, or a single helper that supports both protocols (e.g. via an async context manager variant).
- Whether Site C's `set_current_trace_io` + `update_current_span` post-pattern is intentional divergence or an oversight relative to Site D.
- Whether the input-truncation inconsistency between Sites C/D (truncated vs. full) is intentional (C: truncated for span, full for trace; D: full everywhere) or a latent bug.
- Whether the `metadata` parameter on Site D should also appear on Site C (both are top-level `ainvoke` paths).
- Whether fixing the exception-path leak in Site D is in scope for this refactor or a separate fix.
- No existing tests cover Langfuse trace shape — any new helper will need greenfield test coverage.
