# Stage 3 — Deep Research

> Resolve every open question from Stage 2. Pressure-test the approach.

**Feature:** message-queue
**Date:** 2026-04-25

## Resolved questions

### Q: How does asyncio.Task.cancel() interact with LangGraph's agent.ainvoke()?

- **Method:** Codebase scan of LangGraph, LangChain, and httpx sources in `.venv/`.
- **Finding:** `CancelledError` propagates cleanly through the entire stack:
  - `Pregel.ainvoke` has no catch — propagates immediately from `astream` (`langgraph/pregel/main.py:3388`).
  - `astream`'s outer `except BaseException` catches it only to call `on_chain_error` under `asyncio.shield`, then **re-raises** (`main.py:3163`).
  - The retry loop in `arun_with_retry` catches only `Exception`, not `BaseException` — `CancelledError` passes through (`_retry.py:229`).
  - LangChain middleware (`before_model`, `after_model`, `dynamic_prompt`) has zero `CancelledError` handling.
  - httpx/httpcore handle cancellation safely: `except BaseException` closes the response, dequeues the request, and uses `AsyncShieldCancellation` to close sockets cleanly (`httpcore/_async/connection_pool.py:248`). No dirty connections.
  - `graph.py:210` already has `except (KeyboardInterrupt, asyncio.CancelledError): raise` — correct and sufficient.
- **Implication:** `asyncio.Task.cancel()` is a safe abort mechanism. The running `ainvoke` will terminate, the checkpointer will attempt to flush (under `asyncio.shield`), and httpx connections will be cleaned up. No special cleanup code needed beyond what already exists.

### Q: What is the CLI equivalent of /stop?

- **Method:** Codebase scan of `chat.py`.
- **Finding:** `chat.py:97` already catches `KeyboardInterrupt` in the main loop — it prints a newline and falls through to the `finally` cleanup block. The current behavior is: `Ctrl+C` stops the entire chat loop (exits), not just the current invocation. There's no `/stop` text command in CLI mode. The `input_fn` blocks the event loop synchronously, so there's no concurrent path to inject a stop signal while `invoke_agent` is awaiting.
- **Implication:** Two options for CLI `/stop`: (a) user types `/stop` as text input — but this only works between invocations (while `input()` is waiting), not during one. (b) `Ctrl+C` triggers `KeyboardInterrupt` which propagates through `invoke_agent` (already handled at line 210). Option (b) is the natural CLI idiom. The queue dispatcher should translate `KeyboardInterrupt` into the same abort path as `/stop`. For v1, CLI `/stop` = `Ctrl+C`.

### Q: Should the discard queue be inspectable via a command?

- **Method:** User follow-up implied by the "recover items" requirement.
- **Finding:** The requirement says users "can recover items from the discard queue within an hour." This requires some inspection mechanism. For Telegram, a `/discarded` command is the natural interface. For CLI, typing `/discarded` as text input would work since commands aren't filtered in CLI mode.
- **Implication:** Add a `/discarded` command handler (Telegram) and recognize `/discarded` text input (CLI). The command lists queued messages with timestamps. A `/recover <index>` or `/recover all` command re-enqueues them. Keep it simple — no pagination needed for v1 since the discard queue will rarely have more than a few items.

### Q: How should cron/reminder events be represented?

- **Method:** Codebase scan — no existing cron or reminder infrastructure in commandclaw.
- **Finding:** Commandclaw has no scheduler. The requirement says "server-originated events (cron triggers, scheduled reminders)." These don't exist yet but the queue must accept them when they do. The queue needs a message type field that distinguishes user messages from server events without coupling to a specific scheduler implementation.
- **Implication:** Define `MsgEnvelope.message_type` as a `Literal["user", "control", "server"]` enum. Server events use `message_type="server"` and carry the trigger's intent as `content` (e.g., "Run the daily summary cron job"). The queue treats them identically to user messages for v1. When a scheduler is built later, it calls `queue.put(MsgEnvelope(message_type="server", content=...))` — no queue changes needed.

### Q: Does PTB's /stop handler need to bypass the queue entirely?

- **Method:** Codebase scan of PTB v21 source in `.venv/`.
- **Finding:** With default settings (`max_concurrent_updates=1`, `block=True`), PTB processes updates sequentially. A `/stop` update is not dispatched until the current handler (which is awaiting `invoke_agent`) returns. This means `/stop` cannot fire while the agent is running — it waits in PTB's internal update queue. The lock in `handlers.py` doesn't help either because `/stop` as a `CommandHandler` bypasses the `MessageHandler` entirely (via `~filters.COMMAND` filter).
- **Implication:** `/stop` **must** bypass PTB's sequential dispatch. Two approaches:
  - (a) Set `block=False` on the `MessageHandler` so PTB wraps it in `asyncio.create_task()` and immediately processes the next update. Then `/stop`'s `CommandHandler` fires concurrently and signals the abort.
  - (b) Register the `/stop` handler with `concurrent_updates` enabled at the application level.

  Approach (a) is simpler — change one handler registration, no global concurrency change. The message handler already has per-session serialization via the queue, so making it non-blocking is safe. Register `/stop` in `group=-1` so it's checked before any group-0 handlers.

## Risks surfaced

- **Checkpoint corruption on hard cancel.** LangGraph's `AsyncPregelLoop.__aexit__` flushes the checkpoint under `asyncio.shield`, which should complete. But if the process is killed (not just the task cancelled), the SQLite write may be incomplete. Mitigation: SQLite WAL mode handles this; the checkpointer already uses `aiosqlite` which enables WAL by default.
- **PTB `block=False` changes error handling.** Non-blocking handlers cannot raise `ApplicationHandlerStop` (PTB enforces this). The current handler doesn't use `ApplicationHandlerStop`, so this is safe. But unhandled exceptions in non-blocking handlers are logged by PTB's error handler rather than crashing the bot — make sure the handler's try/except is comprehensive.
- **Discard queue memory leak.** If the bot runs for months without restarts and users `/stop` frequently, the discard queue accumulates entries (even with 1-hour TTL, lazy cleanup only runs on access). Mitigation: cap the discard queue at 1000 entries total across all sessions; evict oldest on overflow regardless of TTL.

## Scope check

- [x] Scope still matches Stage 2 v1
- [ ] Scope has grown — user must decide to split or accept

The `/discarded` and `/recover` commands are a small addition implied by the original requirement ("users can recover items"). No scope expansion beyond what was agreed.
