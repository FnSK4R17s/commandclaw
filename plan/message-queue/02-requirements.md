# Stage 2 — Requirements

> User-facing contract. Record answers verbatim. No solutions yet.

**Feature:** message-queue
**Date:** 2026-04-25

## Users / callers

Both Telegram users and CLI chat users. The queue is a unified abstraction that both channels feed into. Not Telegram-only.

## v1 scope — minimum shippable behavior

1. **Three message classes** enter the queue: user messages (regular text), control commands (`/stop`), and server-originated events (cron triggers, scheduled reminders).
2. **Serial processing** — one agent invocation at a time per session. Messages arriving while the agent is busy are buffered.
3. **`/stop` is an emergency brake** — hard-cancels the running `agent.ainvoke()` via `task.cancel()`, moves all queued messages to a discard queue, responds within 1 second.
4. **Discard queue with 1-hour TTL** — queued messages at the time of `/stop` are recoverable for 1 hour, then permanently deleted.
5. **Queue cap of 200** — when full, the newest message is rejected with an error sent back to the user.

## Out of scope

- External message broker (Redis, RabbitMQ) — in-memory only
- Queue persistence across bot restarts — ephemeral
- Streaming / token-by-token delivery to Telegram
- Sub-agent orchestration or agent team communication
- Priority lanes (server events skipping ahead of user messages)
- `steer` mode (injecting messages into a live LLM stream)
- `collect` mode (batching multiple queued messages into one prompt)

## Acceptance criteria

- [ ] User sends a message, then immediately sends `/stop` — running invocation cancelled, bot confirms stop within 1 second
- [ ] User sends 3 messages rapidly — first processed immediately, second and third queued and processed in order
- [ ] Queued messages at `/stop` time appear in the discard queue and are recoverable for 1 hour
- [ ] Queue at 200 messages rejects the next incoming message with an error response
- [ ] Server-originated events (cron, reminders) enter the queue and process in order alongside user messages
- [ ] CLI chat uses the same queue abstraction as Telegram
- [ ] All existing tests continue to pass — drop-in replacement for the current per-chat lock

## Non-functional constraints

- Queue enqueue/dequeue adds sub-millisecond overhead (in-process, no serialization)
- 200-message cap per session. Memory is cheap.
- One agent invocation at a time per session. Different sessions run concurrently.
- Discard queue entries auto-expire after 1 hour. Lazy cleanup on access is acceptable.

## Open questions

- How does `asyncio.Task.cancel()` interact with LangGraph's `agent.ainvoke()`? Does cancellation propagate cleanly through the middleware stack?
- What is the CLI equivalent of `/stop`? `Ctrl+C`? A typed `/stop`? Both?
- Should the discard queue be inspectable via a command (e.g., `/discarded`) or only programmatically?
- How should cron/reminder events be represented — as synthetic `MsgEnvelope` objects or a separate interface?
- Does PTB's `/stop` handler need to bypass the queue entirely, or can it enter as a priority-0 message?
