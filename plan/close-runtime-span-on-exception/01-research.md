# Stage 1 — Research

> Observation only. No design, no requirements, no solutions.

**Feature:** close-runtime-span-on-exception
**One-liner:** Ensure the Langfuse agent span in agent/runtime.py's invoke_agent closes on exception instead of leaking.
**Date:** 2026-04-22

---

## Existing surface area

Files this feature will touch or depend on:

- `src/commandclaw/agent/runtime.py` — `invoke_agent` function, L132-236. Contains Site D: the manual `__enter__`/`__exit__` span that leaks on exception.
- `src/commandclaw/agent/graph.py` — `TracedGraph.ainvoke`, L408-463. Prior art: manual enter/exit that closes on exception (Site C).
- `src/commandclaw/tracing/langfuse_tracing.py` — Langfuse singleton init, `create_langfuse_handler`, `flush_tracing`. Does NOT contain span lifecycle code; relevant only for understanding flush behavior.
- `pyproject.toml` — `langfuse>=4` (no upper bound). Installed: `4.0.4`.

No tests in `tests/` currently reference Langfuse, tracing, spans, or observations. The eight test files cover vault, git, tools, and agent retry logic only.

---

## Relevant patterns already in the codebase

### Site C — `TracedGraph.ainvoke` (graph.py L408-463): correct prior art

```python
# graph.py L419-441
lf = None
trace_ctx = None
try:
    from langfuse import get_client as get_langfuse
    lf = get_langfuse()
    trace_ctx = lf.start_as_current_observation(
        name=agent_id,
        as_type="span",
        input={"message": user_input[:500]},
    )
    trace_ctx.__enter__()
except Exception:
    lf = None
    trace_ctx = None

try:
    result = await self._graph.ainvoke(input_, config=config, **kwargs)
except Exception:
    if trace_ctx:
        try:
            trace_ctx.__exit__(None, None, None)
        except Exception:
            pass
    raise
```

The success path then calls `trace_ctx.__exit__(None, None, None)` at L459. The exception path (L435-441) calls `__exit__` before re-raising. This is the correct double-close pattern: once on the exception path (raise), once on the success path.

### Site D — `invoke_agent` (runtime.py L184-215): the bug

```python
# runtime.py L184-215
langfuse_ctx = None
try:
    from langfuse import get_client as get_langfuse
    lf = get_langfuse()
    agent_name = settings.agent_id or "commandclaw"
    langfuse_ctx = lf.start_as_current_observation(
        name=agent_name,
        as_type="span",
        input={"message": message},
        metadata={"agent_id": agent_name, "session_id": session_id},
    )
    langfuse_ctx.__enter__()
except Exception:
    langfuse_ctx = None

# Invoke LangGraph agent
result = await agent_executor.ainvoke(
    {"messages": messages},
    config=config,
)

# Close the parent observation
if langfuse_ctx is not None:
    try:
        ai_out = [...]
        langfuse_ctx.update(output=ai_out[-1].content if ai_out else "")
        langfuse_ctx.__exit__(None, None, None)
    except Exception:
        pass
```

The close block (L206-215) only executes when `ainvoke` returns normally. If `ainvoke` raises, execution jumps to the outer `except Exception` at L230, which logs the error and returns an `AgentResult(success=False)` — the close block is never reached. `langfuse_ctx` is never garbage-collected in any predictable way because it holds a live OTEL span context token.

### Second bug at Site D: `langfuse_ctx.update(...)` is broken

`langfuse_ctx` is the `_AgnosticContextManager` object returned by `start_as_current_observation`. Its `__enter__()` return value (the `LangfuseSpan` object) is discarded at L195. The context manager itself does NOT have an `update` method — `_AgnosticContextManager` inherits from `contextlib._GeneratorContextManager` and OpenTelemetry's override; neither defines `update`.

The `update` call at L212 therefore always raises `AttributeError`. This exception is silently swallowed by the `except Exception: pass` at L214. The consequence: even on the success path, the span's output is never set, and `__exit__` is still called (L213 runs before the exception is swallowed — wait: no, the `except` catches the `AttributeError` from L212, so L213 never executes). This means the span is also leaked on the success path if `langfuse_ctx.update(...)` raises.

Correction: Python executes L212 first; if it raises `AttributeError`, the `except Exception: pass` at L214 catches it, skipping L213 (`__exit__`). The span is therefore leaked on both success and exception paths whenever tracing is enabled.

Contrast with graph.py Site C: `lf.update_current_span(output=...)` (L453) is called on the client `lf`, not on `trace_ctx`. The client's method queries the current OTEL context, which still has the span active (since `trace_ctx.__exit__` has not been called yet). This is the correct approach.

### Sites A and B — `with` statement (graph.py L121-131, L163-173): safe

Both guardrail sites use `with lf.start_as_current_observation(...) as span:` — the `with` statement ensures `__exit__` is called on both normal and exception paths. No leak.

---

## Constraints discovered

- **Langfuse SDK version:** `langfuse>=4` (pyproject.toml), installed `4.0.4`. All call sites use the v4 API: `get_client`, `start_as_current_observation`, `propagate_attributes`, `set_current_trace_io`, `update_current_span`.
- **`_AgnosticContextManager` identity:** `start_as_current_observation` returns an `_AgnosticContextManager` (from `opentelemetry.util._decorator`), which is a `contextlib._GeneratorContextManager` subclass. `__enter__` yields and returns the `LangfuseSpan`/`LangfuseGeneration` wrapper. The context manager itself has no `update`, `end`, or Langfuse-specific methods.
- **Span export requires `end()`:** The Langfuse OTEL pipeline uses `LangfuseSpanProcessor(BatchSpanProcessor)`. Its `on_end` hook (which enqueues the span for export) is only called when the OTEL span's `end()` method is invoked. `__exit__` on the context manager is the mechanism that calls `end()`. A span that never receives `__exit__` is never passed to `on_end`, is never queued, and is never exported.
- **`flush_tracing()` does NOT rescue leaked spans:** `flush_tracing` calls `_langfuse_client.flush()`, which calls `_resources.flush()`, which calls `tracer_provider.force_flush()`. `force_flush` only exports spans already in the processor's batch queue. An unclosed span has never been handed to `on_end`, so it is absent from the queue. Verified empirically: starting an OTEL span and calling `force_flush()` without `span.end()` exports zero spans.
- **`atexit` shutdown does NOT rescue leaked spans:** `ResourceManager` registers `self.shutdown` via `atexit.register(self.shutdown)` at init time. `shutdown()` calls `flush()` then stops consumer threads. Same constraint: spans not yet ended are not in the export queue.
- **Dashboard appearance:** A span that is never exported does not appear in the Langfuse dashboard at all — not as "open", not as "incomplete". It is simply missing. The parent trace created by the `CallbackHandler` (from `create_langfuse_handler`) will still appear, but without the parent span wrapper that `invoke_agent` was supposed to contribute.
- **Child span relationship:** The LangChain `CallbackHandler` creates its own child observations inside the OTEL context established by `__enter__`. If `__enter__` succeeded but `__exit__` is never called, the OTEL context variable (`ContextVar`) holding the current span token is never reset. In a long-lived process (Telegram bot, always-on agent), this means subsequent invocations may inherit stale context, causing child spans to be incorrectly parented under a ghost ancestor span.
- **Python ≥ 3.11.** `try/finally` and `try/except/else` both available. `contextlib.asynccontextmanager` available.
- **Ruff:** `E, F, I, N, W, UP`, line-length 100, `target-version = "py311"`. The fix must pass lint.
- **`asyncio_mode = "auto"` and `--strict-markers`:** Any new test must not introduce unregistered markers.
- **Outer `try/except` scope (runtime.py L151, L226-236):** The outer `try` wraps the entire body of `invoke_agent` including `ainvoke`. Its `except` catches all non-interrupt exceptions and returns `AgentResult(success=False)`. The fix must close the span before (or inside) this outer `except` handler, or restructure with `try/finally`.

---

## qmd findings

Both `shikhar-wiki` searches returned no relevant hits (as expected — the personal wiki contains no Python resource-management or OTEL content). No prior knowledge applicable.

---

## Unknowns surfaced

- **Whether the `langfuse_ctx.update(output=...)` at L212 silently fails in production:** Confirmed above that `_AgnosticContextManager` has no `update` method, so this line raises `AttributeError` in every invocation where tracing is enabled. The `except Exception: pass` swallows it. This means the span is currently leaked on all paths (success and failure), not just the exception path. Severity is higher than originally stated in the tracing-span-helper research.

- **Stale context variable hazard:** Whether the unreset `ContextVar` token from an unclosed span actually causes incorrect parenting in subsequent calls depends on whether Langfuse/OTEL detaches the context token in `__exit__`. Confirmed by OTEL source: `start_as_current_span` attaches a new context on `__enter__` and detaches it on `__exit__`. If `__exit__` is never called, the old context remains attached for the lifetime of the async task or thread. In an `asyncio` environment with task-per-request, this is scoped to the task and cleaned up when the task completes. In a shared-event-loop architecture (e.g., multiple Telegram messages handled concurrently), stale context may bleed between concurrent handlers if they share the same task or if context is improperly propagated. This is an open question about the bot's concurrency model.

- **Whether the `langfuse_ctx.update(output=...)` secondary bug should be fixed in the same commit or separately:** It is at the same site (L212) and is discovered as part of this investigation. Fixing the leak alone (adding `try/finally`) without also fixing the `update` call leaves a broken method call that raises and is swallowed on every successful invocation.

- **Whether `metadata` on Site D (construction-time `metadata={"agent_id": ..., "session_id": ...}`) should be mirrored on Site C (TracedGraph.ainvoke):** Site C has no `metadata` at construction. This inconsistency was noted in the tracing-span-helper research and remains unresolved.

- **No Langfuse test coverage:** Confirmed — zero test files reference Langfuse, tracing, or span objects. Any fix will require greenfield test coverage using a mock or fake OTEL span exporter.

---

## Overlap with tracing-span-helper feature

The `tracing-span-helper` feature (`plan/tracing-span-helper/`) was identified in its own Stage 1 research as an opportunity to fix this exact bug (noted as Site D, "resource leak"). The tracing-span-helper research explicitly called out:

> "Site D has an exception-path resource leak: if `agent_executor.ainvoke` raises, `langfuse_ctx.__exit__` is never called."
> "Whether fixing the exception-path leak in Site D is in scope for this refactor or a separate fix."

If `tracing-span-helper` is implemented first and replaces Site D with a shared context manager helper that wraps the `try/finally` pattern internally, this bug disappears as a side effect. Conversely, this feature (`close-runtime-span-on-exception`) can be fixed independently and locally without waiting for the helper refactor. The two features are not mutually exclusive; this fix is a strict subset of what tracing-span-helper would accomplish at Site D.
