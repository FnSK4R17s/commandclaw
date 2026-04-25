# Stage 1 — Research

> Observation only. No design, no requirements, no solutions.

**Feature:** message-queue
**One-liner:** Priority message queue with abort signals and system events for agent dispatch
**Date:** 2026-04-25

## Existing surface area

Modules, files, configs, and tests this feature will touch or depend on.

### Message entry points

- `src/commandclaw/telegram/handlers.py` — `create_message_handler` returns a PTB handler closure. All Telegram text messages (excluding commands) flow through here. Currently serializes per-chat via `asyncio.Lock` in an `OrderedDict` LRU cache (`_chat_locks`, cap 1024). No queue, no priority, no abort.
- `src/commandclaw/telegram/bot.py` — `start_bot` builds the PTB Application. `/start` is the only command handler. The message handler is registered dynamically inside `_post_init`. `_post_shutdown` tears down MCP + checkpointer + tracing.
- `src/commandclaw/telegram/sender.py` — `send_message` (chunked, Markdown-first with plain-text fallback) and `send_error_alert`. Outbound only.
- `src/commandclaw/chat.py` — `chat_loop` is a synchronous `input()`-based REPL. No async queue — the event loop blocks on `input_fn`. Bootstrap/hatch mode runs one synthetic message then switches to normal chat.
- `src/commandclaw/cli.py` — `main()` dispatches to `run_chat()` or `start_bot()`. Thin glue.

### Agent invocation

- `src/commandclaw/agent/graph.py` — `invoke_agent` is the sole agent entry point. Retry loop: `max_retries` attempts with exponential backoff (`retry_base_delay * 2^attempt`). Explicitly re-raises `KeyboardInterrupt` and `asyncio.CancelledError` (line 210). No abort signal, no timeout, no cancellation token passed to `agent.ainvoke`.
- `src/commandclaw/agent/context.py` — `CommandClawContext` dataclass passed as `context=` to `agent.ainvoke`. Contains `vault_path`, `agent_id`, `api_key`, `user_id`, `session_id`. No abort field.
- `src/commandclaw/agent/middleware.py` — `input_guardrails` and `output_guardrails` check messages before/after the LLM. No awareness of queue or abort state.

### Configuration

- `src/commandclaw/config.py` — `Settings` Pydantic model. Relevant fields: `max_retries` (int, default 3), `retry_base_delay` (float, default 1.0), `telegram_allowed_chat_ids` (list[int]), `telegram_chunk_size` (int, default 4000). No queue-related settings exist.

### Tests

- `tests/unit/test_telegram_handlers.py` — covers lock LRU cache (5 tests) and handler dispatch (9 tests). Handler tests use mock `Update`/`Context` objects with `monkeypatch` on `invoke_agent`.
- `tests/unit/test_chat.py` — covers normal chat loop (8 tests) and bootstrap path (4 tests). Uses injectable `input_fn`/`print_fn`.
- `tests/agent/test_agent_tools.py` — covers `invoke_agent` retry logic (2 tests: recovery and exhaustion) using a fake agent class.

## Relevant patterns already in the codebase

### Factory + injectable IO (chat.py, hatching.py)

`chat_loop` accepts `input_fn` and `print_fn` callables, making the entire REPL testable without real stdio. The message queue dispatcher should follow the same pattern — accept callables or protocols for the agent invocation and reply delivery, so tests can inject fakes.

### Per-chat lock serialization (handlers.py:25-35)

`_lock_for(chat_id)` is an LRU `OrderedDict` of `asyncio.Lock` instances, capped at 1024. This is the pattern the message queue replaces. The LRU eviction logic is correct but the approach has no queue depth, no back-pressure, no priority, and no abort.

### Agent result dataclass (context.py)

`AgentResult(output, success, error)` is the return type from `invoke_agent`. A cancelled invocation would need a new state — either extend `AgentResult` with a `cancelled` flag or use `success=False` with a specific error string.

### Guardrails engine class pattern (guardrails/engine.py)

`GuardrailsEngine` wraps per-instance state with no globals. The message queue should follow the same pattern — a class with explicit lifecycle, testable by constructing fresh instances.

### PTB bot_data sharing (bot.py)

The agent, MCP client, checkpointer close function, and settings are stored in `application.bot_data` — a dict shared across all handlers and lifecycle hooks. The message dispatcher would be stored here alongside the agent.

## Constraints discovered

- **Python 3.11+** — `asyncio.TaskGroup` is available (3.11+). `asyncio.PriorityQueue` has existed since 3.4.
- **ruff lint rules** — `E,F,I,N,W,UP` with `line-length = 100`.
- **asyncio_mode = "auto"** in pytest — async test functions work without decorators.
- **strict-markers** — any new `@pytest.mark.foo` must be registered in `pyproject.toml`.
- **PTB 21.x** — python-telegram-bot uses its own event loop. Handlers are async coroutines dispatched by PTB's `Application`. `run_polling` blocks the main thread. `_post_init` and `_post_shutdown` are the async lifecycle hooks.
- **LangGraph `agent.ainvoke`** — the compiled agent's invoke method. Accepts `config` and `context` kwargs. No built-in cancellation token, but `asyncio.CancelledError` propagation works (already handled in `invoke_agent`).
- **No external message broker** — the current architecture is entirely in-process. Adding Redis/RabbitMQ would be a scope escalation.

## qmd findings (if enabled)

No relevant hits in `shikhar-wiki` collection. The wiki covers graph algorithms and historical topics, not message queue design patterns.

## Unknowns surfaced

- Should the CLI chat path (`chat.py`) also use the message queue, or is it Telegram-only? The CLI is synchronous (`input()` blocks), which doesn't naturally fit an async queue.
- What queue modes are needed for v1? Openclaw has 6 modes (`steer`, `followup`, `collect`, `interrupt`, `queue`, `steer-backlog`). Commandclaw likely needs only 2-3.
- Should abort cancel the current LangGraph invocation mid-flight (via `asyncio.Task.cancel`), or just prevent the next queued message from running?
- What happens to queued messages when abort fires? Drop all? Keep them? Run the next one?
- Should system events be visible to the user (e.g., sent as Telegram messages) or only injected into the agent's prompt?
- Does the queue need persistence across bot restarts, or is in-memory sufficient?
- What is the expected queue cap? Openclaw defaults to 20 with a `summarize` drop policy. Is that appropriate for Telegram where messages are typically short?
