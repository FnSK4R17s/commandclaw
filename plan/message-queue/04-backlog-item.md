# Priority Message Queue

> Replace the per-chat asyncio lock with a session-scoped message queue that supports `/stop` hard-cancel, a 1-hour discard queue for interrupted messages, and server-originated events — so the agent can be stopped mid-thought and the user never loses context.

This is an idea file. It describes a feature for an existing codebase at the right level of abstraction — concrete enough to be actionable, abstract enough to not over-specify implementation. Share it with an implementing LLM agent alongside the three stage files under `plan/message-queue/` and let the agent propose a concrete patch plan before writing any code.

## What changes

Today, `telegram/handlers.py` serializes per-chat messages with an `asyncio.Lock` stored in an LRU `OrderedDict`. When a user sends a message while the agent is running, the new message blocks at `async with _lock_for(chat_id)` until the current invocation completes. There is no way to cancel a running invocation, no queue depth visibility, no concept of control messages, and no mechanism for server-originated events like cron triggers. The CLI path in `chat.py` is worse — `input()` blocks the event loop synchronously, so no concurrent signals are possible at all.

**The core problem is that message dispatch and agent invocation are fused into one synchronous await — there is no seam between "accepting a message" and "processing a message," so nothing can interrupt, reorder, or inspect the pipeline.** After this feature, a `SessionQueue` owns the buffer between arrival and processing. Messages are enqueued instantly (sub-millisecond) and processed serially by a drain loop. `/stop` bypasses the queue, cancels the running `asyncio.Task`, moves pending messages to a time-limited discard queue, and responds immediately. Server events enter the same queue as user messages. Both Telegram and CLI feed into the same abstraction.

## Touchpoints

**`message/envelope.py`** — the message unit that flows through the system. A frozen dataclass with `session_id`, `content`, `message_type` (user / control / server), and `timestamp`. This is a new module because the current codebase has no message abstraction — text strings flow directly from handler to `invoke_agent`. The envelope decouples "what arrived" from "how to process it."

**`message/session_queue.py`** — the per-session queue with a drain loop. Owns an `asyncio.Queue`, an abort `asyncio.Event`, and a discard list with TTL. Replaces `_lock_for` in `handlers.py`. This is the core of the feature. It is a new module because the queue lifecycle (create on first message, drain serially, abort on `/stop`, expire discards) is a distinct responsibility from message handling or agent invocation.

**`message/discard.py`** — the discard queue with 1-hour TTL and recovery. Stores `MsgEnvelope` objects with expiry timestamps. Provides `list_discarded()` and `recover()`. Separated from `session_queue.py` because the discard lifecycle (TTL, inspection, recovery) is orthogonal to the active queue logic.

**`message/dispatcher.py`** — the router that maps incoming messages to the correct `SessionQueue`. Maintains a `dict[str, SessionQueue]`. Both Telegram handlers and CLI chat call `dispatcher.dispatch(envelope)`. This is the unified entry point that makes the queue channel-agnostic.

**`telegram/handlers.py`** — changes from a lock-based handler to a thin adapter that constructs a `MsgEnvelope` and calls `dispatcher.dispatch()`. The `_lock_for` mechanism and `_chat_locks` OrderedDict are removed entirely. The `MessageHandler` registration changes to `block=False` so PTB dispatches updates concurrently, enabling `/stop` to fire while the agent is running.

**`telegram/bot.py`** — adds a `CommandHandler("stop", _stop_command)` in `group=-1` (higher priority than the message handler in group 0). The `/stop` handler calls `dispatcher.abort(session_id)`. Also adds `/discarded` and `/recover` command handlers. The dispatcher is stored in `bot_data` alongside the agent.

**`chat.py`** — replaces the `while True: input(); invoke_agent()` loop with queue-based dispatch. `KeyboardInterrupt` (Ctrl+C) translates to the same abort path as `/stop`. Recognizes `/stop` and `/discarded` as text commands.

**`agent/graph.py`** — `invoke_agent` gains an optional `abort_event: asyncio.Event` parameter. The retry loop checks `abort_event.is_set()` before each attempt. The running `agent.ainvoke()` is wrapped in an `asyncio.Task` that can be cancelled externally when the event fires.

**`config.py`** — adds `queue_cap` (int, default 200) and `discard_ttl_seconds` (int, default 3600) settings.

## Workflow

### Normal message flow

1. User sends a text message in Telegram (or types input in CLI).
2. The channel adapter constructs a `MsgEnvelope(message_type="user")` and calls `dispatcher.dispatch(envelope)`.
3. The dispatcher finds or creates the `SessionQueue` for the session and enqueues the envelope.
4. The queue's drain loop picks up the envelope, calls `invoke_agent`, and sends the result back through the channel adapter.

### /stop abort flow

1. User sends `/stop` in Telegram (or presses Ctrl+C in CLI).
2. The `/stop` handler calls `dispatcher.abort(session_id)`.
3. The dispatcher signals the session's `abort_event`, which cancels the running `asyncio.Task` wrapping `invoke_agent`.
4. All pending messages in the session queue are moved to the discard queue with a 1-hour TTL.
5. The bot responds immediately: "Agent stopped. N messages moved to discard queue."

### Discard recovery flow

1. User sends `/discarded` to see what was interrupted.
2. The handler lists discarded messages with timestamps and indices.
3. User sends `/recover 2` (or `/recover all`) to re-enqueue specific items.
4. Recovered messages enter the back of the active queue and are processed normally.

## Example

> **Scenario.** A Telegram user sends "summarize my daily notes" which triggers a long agent run. While waiting, they send two more messages. They get impatient and send `/stop`.

Input sequence (Telegram chat):

```
[12:00:01] User: summarize my daily notes
[12:00:05] User: also check if MEMORY.md needs updating
[12:00:08] User: and create a new daily note for today
[12:00:12] User: /stop
```

What happens:

1. Message 1 enqueues and starts processing immediately — `invoke_agent` begins.
2. Messages 2 and 3 enqueue (positions 1 and 2 in the queue) while message 1's agent run is in flight.
3. `/stop` fires via the `CommandHandler` in group -1 (concurrently, since `MessageHandler` is `block=False`).
4. The running task for message 1 is cancelled via `task.cancel()`. Messages 2 and 3 are moved to the discard queue.
5. The bot responds immediately.

Output (Telegram):

```
[12:00:12] Bot: Agent stopped. 2 messages moved to discard queue (expires 13:00).
           Use /discarded to view, /recover <n> to re-queue.
```

If the user then sends `/discarded`:

```
[12:00:15] Bot: Discarded messages (expires 13:00:12):
           1. [12:00:05] also check if MEMORY.md needs updating
           2. [12:00:08] and create a new daily note for today
           /recover <n> or /recover all
```

## Stack

| Component | Technology | Status |
|-----------|-----------|--------|
| Message envelope | Python dataclass | To build |
| Session queue | `asyncio.Queue` + drain loop | To build |
| Discard queue | In-memory list with TTL | To build |
| Message dispatcher | Dict of SessionQueues | To build |
| Telegram handler adapter | python-telegram-bot v21 | Built (to modify) |
| CLI chat adapter | `chat.py` with injectable IO | Built (to modify) |
| Agent invocation | LangGraph `agent.ainvoke` | Built (to modify) |
| Abort signal | `asyncio.Event` + `Task.cancel()` | Available |
| Per-session serialization | `asyncio.Queue` (replaces `asyncio.Lock`) | Available |
| Settings | Pydantic `Settings` | Built (to extend) |

## Acceptance criteria

- [ ] User sends a message, then immediately sends `/stop` — running invocation cancelled, bot confirms stop within 1 second
- [ ] User sends 3 messages rapidly — first processed immediately, second and third queued and processed in order
- [ ] Queued messages at `/stop` time appear in the discard queue and are recoverable for 1 hour
- [ ] Queue at 200 messages rejects the next incoming message with an error response
- [ ] Server-originated events (cron, reminders) enter the queue and process in order alongside user messages
- [ ] CLI chat uses the same queue abstraction as Telegram
- [ ] All existing tests continue to pass — drop-in replacement for the current per-chat lock

## Out of scope

- External message broker (Redis, RabbitMQ)
- Queue persistence across bot restarts
- Streaming / token-by-token delivery to Telegram
- Sub-agent orchestration or agent team communication
- Priority lanes (server events skipping ahead of user messages)
- `steer` mode (injecting into a live LLM stream)
- `collect` mode (batching queued messages into one prompt)

## What makes this hard

1. **PTB's sequential dispatch blocks `/stop` behind the running handler.** With default settings (`max_concurrent_updates=1`, `block=True`), PTB will not process the `/stop` update until the current `invoke_agent` returns — defeating the purpose. The fix is setting `block=False` on the `MessageHandler` so PTB wraps it in `asyncio.create_task()` and proceeds to the next update. This changes error handling semantics: unhandled exceptions are logged by PTB's error handler instead of propagating. The handler's try/except must be comprehensive.

2. **Task cancellation during LangGraph checkpoint flush.** When `asyncio.Task.cancel()` fires, LangGraph's `AsyncPregelLoop.__aexit__` flushes the checkpoint under `asyncio.shield`. This should complete, but if the process is killed (not just the task), the SQLite write may be partial. SQLite WAL mode (enabled by default in `aiosqlite`) handles this, but the implementing agent should verify WAL is active and add a test that cancels mid-invocation and checks checkpoint integrity.

3. **CLI input blocks the event loop.** `input()` is synchronous — while it's waiting for user input, no async tasks run. The queue's drain loop can't process messages during `input()`. The implementing agent needs to run `input()` in a thread (via `asyncio.get_event_loop().run_in_executor(None, input, prompt)`) so the event loop stays free for the queue drain and abort signals.

## Why this works

The dispatcher is the mailbox; the session queue is the inbox; the drain loop is the courier. This three-layer split works because commandclaw already established the pattern of separating concerns into testable, per-instance classes — `GuardrailsEngine`, `TracingManager`, `MCPClient` all encapsulate lifecycle state without globals. The message queue follows the same shape: construct a `SessionQueue` per session, inject it where the lock used to be, test it by enqueuing and draining without a real agent. The discard queue is the same pattern again — a time-bounded list with no external dependencies. **The reason this approach succeeds where bolting cancellation onto the existing lock would fail is that the lock fuses "accept" and "process" into one atomic await — you can't cancel half of an `async with`. The queue splits that atom, and everything follows from the split.**

## References

The implementing agent should read these before starting:

- [Research](01-research.md)
- [Requirements](02-requirements.md)
- [Deep Research](03-deep-research.md)

## Note

This document is intentionally abstract. Concrete file edits, function signatures, and test cases depend on the state of the codebase at implementation time. Paste this document into an implementing agent's context along with the three referenced stage files, and let the agent propose a concrete patch plan before writing code.
