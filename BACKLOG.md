# CommandClaw — Enterprise Backlog

> Gap analysis vs OpenClaw 2026.2.16 → prioritized backlog to get CommandClaw production-ready for multi-tenant enterprise use.
>
> See [architecture/](architecture/) for the per-repo design docs. This file is the **what's missing** companion.

## TL;DR

CommandClaw's **gateways** (`commandclaw-gateway` for LLMs, `commandclaw-mcp` for tools) are production quality. The **runtime** is basic — fine for one hobby agent, not ready for governed enterprise use. The **memory service** is a stub. There is no **scheduler**. Critical observability and guardrail paths **bypass Telegram**.

Expect two quarters of focused work to close P0 + P1.

---

## P0 — production blockers

### 1. Session state is not durable

- [src/commandclaw/agent/runtime.py](src/commandclaw/agent/runtime.py) uses `MemorySaver()` → in-process RAM only. Process restart wipes every conversation.
- [src/commandclaw/agent/graph.py:342](src/commandclaw/agent/graph.py) hardcodes `thread_id = f"{agent_id}/inner"` — all concurrent chats for one agent **share one checkpointer slot**. State collision risk.
- OpenClaw uses a per-agent file JSON store + per-session `.jsonl` transcripts + write-locks.

**Fix:** swap `MemorySaver` → `langgraph-checkpoint-sqlite` (already a listed dep, unused) or a Redis-backed checkpointer. Namespace `thread_id` by actual session key, not agent_id.

### 2. No session write-locking

- OpenClaw: per-session `.jsonl.lock` file, in-process re-entrancy ref-count, 60s watchdog, `DEFAULT_MAX_HOLD_MS=5min`, stale detection on dead PID or 30-min age.
- CommandClaw: nothing. Two processes writing the same session race.

**Fix:** mirror `session-write-lock.ts` — file lock + PID + watchdog. Matters the moment more than one runtime pod runs.

### 3. No lane system

OpenClaw has three-tier concurrency:

| Layer | Purpose |
|---|---|
| **Session lane** (`session:{sessionId}`) | Serializes per-session turns |
| **Global lanes** (Main / Cron / Subagent / Nested) | Caps concurrent runs per class |
| **Lane generation counter** | Bumped on SIGUSR1 restart to drain stuck tasks |

CommandClaw has one `asyncio.Lock` per `chat_id` in [src/commandclaw/telegram/handlers.py:20](src/commandclaw/telegram/handlers.py). No global cap. No subagent lane. No restart recovery. Stuck task blocks the queue forever.

**Fix:** port `command-queue.ts` semantics — `LaneState {queue, activeTaskIds, maxConcurrent, generation}`, lane reset on restart, per-session lane on top of per-global-class lane.

### 4. No abort / cancellation

- User sends a new message while agent is running → second message queues behind the lock. No way to cancel the in-flight turn.
- OpenClaw: `QueueMode` values `steer` / `followup` / `collect` / `steer-backlog` / `interrupt` / `queue`, plus `queueDrop: old|new|summarize`. `/stop` routes to a separate control lane that bypasses the serializer.

**Fix:** expose an abort signal per run, wire `/stop` on Telegram to a control lane, add `QueueMode` selection per channel.

### 5. Telegram path bypasses the guardrail graph

Security hole.

- [src/commandclaw/agent/runtime.py](src/commandclaw/agent/runtime.py) (Telegram) uses flat `create_react_agent(llm, tools)` — no guardrails, no tracing span tree.
- [src/commandclaw/agent/graph.py](src/commandclaw/agent/graph.py) (CLI only) runs `load_identity → input_guardrails → agent → output_guardrails` with `TracedGraph`.

**Fix:** consolidate to one agent construction path. Telegram must run through the same StateGraph as CLI.

### 6. No model failover

- [src/commandclaw/agent/retry.py](src/commandclaw/agent/retry.py) retries the **same** model with exponential backoff.
- OpenClaw: `advanceAuthProfile()` rotates OAuth profiles → `FailoverError` → fallback chain. Context-window guard throws `FailoverError` pre-dispatch if model's window is too small.
- CommandClaw's **gateway** has fallback chains (`FallbackChain`), but the runtime doesn't use them — no `model.fallbacks` config surface.

**Fix:** expose `model.primary + fallbacks` in agent config; on gateway-reported failover, switch client. Add context-window pre-check.

### 7. Auth profile rotation + cooldowns

OpenClaw: per-profile cooldown map, rate-limit → mark profile → rotate → when exhausted, throw. Critical when running on subscription OAuth (Anthropic Pro/Max).

CommandClaw: no concept of multiple auth profiles per provider.

**Fix:** if you want to support subscription-level auth alongside API keys, required. Otherwise defer.

### 8. Memory service is vapor

- [/apps/commandclaw-memory/](../commandclaw-memory/) has **zero Python files**. README + logo only.
- "Memory" today = `vault/memory.py` reading `MEMORY.md` + last 2 daily notes into the system prompt on every turn. No search, no RRF, no distillation.
- OpenClaw: `memory-lancedb` extension with cosine recall, importance/category metadata, CRUD tools.

**Fix:** ship v0 of the memory service per [guiding_docs/MEMORY_PLAN.md](guiding_docs/MEMORY_PLAN.md). Even LanceDB + markdown pass-through beats "inject the whole MEMORY.md every turn."

### 9. No scheduler / cron / heartbeat

- `HEARTBEAT.md` is read into the prompt and that is the full implementation.
- `grep -r cron|schedule|apscheduler|celery` in runtime → **zero hits**.
- OpenClaw cron: `at` / `every` / `cron` schedule types, session-scoped reminders, min-refire-gap (prevents spin loops), per-run telemetry, webhook delivery mode, legacy notify fallback.

**Fix:** add APScheduler or `croniter` + async worker. Persist jobs to Redis or SQLite. Implement `delivery: announce|webhook|none`, `wakeMode: next-heartbeat|now`, minimum refire gap.

### 10. No restart sentinel

OpenClaw writes a `RestartSentinel` struct (channel, to, accountId, threadId, sessionKey, kind, status) to disk before SIGUSR1 self-restart; next boot reads it, replies to the original channel/thread. Without this, the bot goes silent after any update.

**Fix:** replicate the pattern. Only restart on update success — a failed build + restart = crash loop.

---

## P1 — enterprise polish

### 11. No streaming to the channel

CommandClaw waits for full completion, sends one Telegram message. OpenClaw: draft-stream previews, 30-char debounce on first update, edit-in-place on finalize. Users feel a 30-second silence in CommandClaw.

### 12. No abort semantics on the agent run

`ainvoke` is not cancellable mid-tool-call. Wrap in `asyncio.Task`; propagate `CancelledError` through tool executors; honor in LLM gateway (send `abort` to upstream if provider supports).

### 13. No multi-agent orchestration

- `Settings` = one agent. `spawn-agent.sh --admin {agent_id}` is shell-only, no runtime hook.
- No subagent lane, no parent-child session tracking, no depth cap.
- OpenClaw: `:subagent:` prefix in session key, `spawnDepth` field, separate subagent lane.

**Fix:** add `SubagentRunner` with session-key prefixing, depth limit, independent lane cap.

### 14. Telegram feature parity

Missing vs OpenClaw 2026.2.16:

- [ ] Reaction events as system messages (`channels.telegram.reactionNotifications`)
- [ ] Inline button `style` support (primary/success/danger)
- [ ] Draft-stream preview with edit-in-place
- [ ] `replyToMode: all` threaded replies
- [ ] `streamMode: off|partial|on` knob
- [ ] Topic-thread session routing (`message_thread_id` preservation on outbound)
- [ ] Control-lane routing for `/stop`, `stop` abort commands
- [ ] Inbound media 20MB limit handling without dropping text

### 15. No admin surface on the runtime

Gateway has `/keys`, `/teams`, `/orgs`, `/audit`, `/spend`. Runtime has **none**. No `/health`, `/ready`, `/metrics`, `/admin/reload`, `/admin/flush-traces`.

**Fix:** add a FastAPI sidecar on the runtime: `/health`, `/ready`, `/metrics`, `/sessions`, `/sessions/{id}/abort`, `/sessions/{id}/reset`, `/runs/active`.

### 16. Usage / billing UI missing

Gateway tracks spend per key/team/org. Runtime has no user-visible usage surface. OpenClaw: `usage.status`, `usage.cost`, `sessions.usage.timeseries` with p95 latency, cache-token breakdown.

**Fix:** Grafana dashboard + a `usage` CLI + Telegram `/usage` command.

### 17. Presidio never imported

`pyproject.toml` lists `presidio-analyzer` + `presidio-anonymizer`. Neither imported anywhere. `guardrails/actions.py:38` uses bare `re`. Either delete the deps or wire them into the pipeline.

### 18. Guardrail weakness

NeMo classification checks if the model's own response contains `"can't do that"` / `"blocked"` — string match on refusal language. Adversarial prompts evade this. Fix: classifier-based input detection (Presidio + NeMo's jailbreak rails + a real toxic-content classifier).

### 19. No plugin SDK

OpenClaw: `@openclaw/plugin-sdk` with `register(api)` pattern, in-tree workspace packages. CommandClaw: skills are markdown. Fine for prompt-level capabilities; insufficient for channel integrations (Discord, Slack, iMessage).

**Fix:** if you want OpenClaw-style channel breadth, ship `commandclaw-sdk` — entry-point-based plugin discovery, `register(api)` with `api.register_tool / register_cli / register_gateway_method / register_channel`.

### 20. No device-auth / mobile pairing

CLI-only today. If a mobile client is ever planned, replicate OpenClaw's v2 device token (pipe-delimited + nonce) and 6-char pairing code flow.

---

## P2 — hardening and hygiene

### 21. Sessions not garbage-collected

OpenClaw: daily/idle reset policies per channel type, configurable reset hour. CommandClaw: sessions live forever in RAM until process dies.

### 22. No compaction

OpenClaw: `splitMessagesByTokenShare` with chunk-ratio tuning, tool-result detail stripping before summarization (security: untrusted tool output never reaches compaction LLM), auto-compaction on context overflow (max 3 attempts).

CommandClaw: none. When context fills, the next turn fails.

**Fix:** add compaction node to the graph. **Strip tool-result details before summarizing** — this is the subtle point most implementations miss.

### 23. No hook system

OpenClaw's 20 hook names (`before_model_resolve`, `before_compaction`, `after_tool_call`, `tool_result_persist`, `before_message_write`, `session_start`/`end`, `gateway_start`/`stop`, etc.) give plugins surgical lifecycle access.

CommandClaw has zero plugin hooks.

**Fix:** start with `before_llm_call`, `after_tool_call`, `session_start`, `session_end`. Expand later.

### 24. No `allowFrom` / RBAC at the channel layer

OpenClaw: prefix-normalized `allowFrom` (`user:`, `discord:`, `pk:`, `<@id>`), `dmPolicy`, per-account `commands.allowFrom`, per-button `allowedUsers`.

CommandClaw Telegram: no allowlist. Anyone who finds the bot token talks to it.

**Fix:** `channels.telegram.allowFrom: [user_id, ...]` with normalization. Reject on mismatch.

### 25. No audit log in the runtime

Gateway has an immutable audit log. Runtime has none — no record of *who* sent *what* message, when, which tools ran, what the agent returned. Enterprise compliance will want this.

**Fix:** emit audit events on every turn (user_id, session_id, tool_calls, tokens, cost, trace_id) to a structured log or Langfuse tag.

### 26. Test gaps

Untested: `graph.py` (StateGraph, guardrail nodes, TracedGraph), `guardrails/engine.py`, `langfuse_tracing.py`, `telegram/handlers.py`. MCP gateway tests directory exists but appears empty.

**Fix:** pytest coverage on graph node wiring, guardrail pass/fail cases, Telegram lock behavior under concurrent messages.

### 27. Container-per-agent doesn't scale

512MB × N agents = your server. Plus every agent is a full Python runtime. OpenClaw: one daemon, many sessions.

**Fix:** decide whether CommandClaw is *one-container-per-agent* (current) or *one-runtime-many-tenants* (needed for enterprise). If the latter, add multi-tenancy: `tenant_id` on every session, quota per tenant, isolated vault paths.

### 28. No observability on Telegram path

Telegram mode has no `TracedGraph` wrapper. Langfuse gets tool + LLM events via `CallbackHandler`, but no outer session span. Hard to debug in production.

---

## Prioritized roadmap

### Sprint 1 — durable session foundation (P0 1–5)

1. Swap `MemorySaver` for SQLite checkpointer, namespace `thread_id` correctly.
2. Port OpenClaw's session write-lock + watchdog.
3. Implement lane system: per-session + global (Main / Cron / Subagent), with generation counter.
4. Consolidate Telegram and CLI onto the same guardrail graph.
5. Add abort / control-lane for `/stop`.

### Sprint 2 — resilience (P0 6–10)

6. Model failover config + runtime support.
7. Context-window guard pre-dispatch.
8. Minimum viable `commandclaw-memory` — LanceDB + schema validation + REST.
9. APScheduler-backed cron with `delivery: announce|webhook`, min refire gap.
10. Restart sentinel for self-update continuity.

### Sprint 3 — enterprise polish (P1 11–20)

11. Streaming to channel + edit-in-place draft preview.
12. Runtime admin FastAPI sidecar + `/usage`, `/sessions`, `/runs`.
13. `allowFrom` normalization + `dmPolicy` on Telegram.
14. Wire Presidio or delete the deps.
15. Plugin SDK v0 with `register(api)` pattern.

### Sprint 4 — hardening (P2 21–28)

16. Session reset policies (daily + idle).
17. Compaction with tool-result stripping.
18. Hook system (12 core hooks).
19. Audit log in runtime.
20. Multi-tenant model if scaling beyond container-per-agent.

---

## What to keep as-is

- LLM gateway (`commandclaw-gateway`) — already production quality. Don't rewrite.
- MCP gateway (`commandclaw-mcp`) — phantom tokens + session pool + circuit breaker + Cerbos are strong.
- Vault-is-control-plane thesis — OpenClaw validates the opposite design and neither is wrong; ours is the right fit for governed enterprise agents.
- Docker-per-agent isolation — keep as *an* option; add multi-tenant mode beside it.

---

## The hardest truth

Most of the OpenClaw 2026.2.16 changelog is fixes for edge cases that **only exist once you have sessions, cron, device auth, and multi-channel routing**. CommandClaw hasn't hit those edges yet because the surface is too small. The gaps above are not bugs — they are absent implementations. The architecture is sound; the runtime is early.
