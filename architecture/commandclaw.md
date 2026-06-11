# commandclaw — the agent runtime (Rust rebuild)

> The agentic layer. A greenfield Rust rewrite. It receives a message, runs an agent loop, and — when a task needs deterministic code changes — delegates a *Spec* to CKRV across a thin MCP seam and relays the verified result back.

This document describes the **greenfield Rust rebuild**. The previous Python/LangGraph runtime — LangChain execution loop, Docker-per-agent, Presidio/NeMo guardrails, Langfuse tracing — is **superseded and discarded**; see [ADR-0001](../docs/adr/0001-rebuild-commandclaw-rust.md) for why. Canonical vocabulary lives in [CONTEXT.md](../CONTEXT.md); the active milestone is [plan/M1-delegation-slice.md](../plan/M1-delegation-slice.md).

## Why it exists

CommandClaw is the **agent**: the conversational, memory-bearing system the user talks to. It decides *what* to do and *whether* to act. Its counterpart, **CKRV** (Chakravarti), is a deterministic `spec → verified-diff` pipeline that decides *how* and proves *done*. CommandClaw never edits code in an open-ended loop itself — when a task requires deterministic code changes, it authors a *Spec* and hands it to CKRV across the **Seam** (CKRV's MCP server), then awaits a verified diff/PR. (Full glossary in [CONTEXT.md](../CONTEXT.md).)

The rebuild is **learning-first** (ADR-0001): the goal is to understand agent internals by hand-rolling the loop, not to ship a commodity framework. The agent loop is the prize — built by hand, not delegated to a library.

## What exists now (S0–S2)

The project is **mid-M1**. Only the front-half plumbing is built, and the loop itself is still a single turn. Precise current state:

| Piece | File | State |
|---|---|---|
| Workspace scaffold (S0) | [Cargo.toml](../Cargo.toml) | `[workspace] members = ["crates/*"]`, edition 2024, resolver 3. Shared deps: `tokio`, `anyhow`. Crates are added per build step. |
| Binary crate | [crates/commandclaw/Cargo.toml](../crates/commandclaw/Cargo.toml) | Deps: `teloxide` (Telegram), `async-openai` (model), `dotenvy` (env). |
| Telegram channel (S1) | [crates/commandclaw/src/main.rs](../crates/commandclaw/src/main.rs) | `teloxide::repl` receive/send loop; chat-id allow-list via `COMMANDCLAW_ALLOWED_CHAT_IDS` (empty = open). |
| Agent-loop seam (S2) | `main.rs` → `respond()` | **Single-turn** model call. This is the function that grows into the real tool-calling loop. |
| Model layer (S2) | [crates/commandclaw/src/model.rs](../crates/commandclaw/src/model.rs) | `ModelClient` over an OpenAI-compatible endpoint. Env: `OPENAI_API_KEY`, `OPENAI_BASE_URL` (optional), `COMMANDCLAW_MODEL` (default `gpt-4o-mini`). |

Round-trip today: **Telegram message → `respond()` → one `ModelClient::chat` call → reply.** No history, no tools, no delegation yet. Configuration is via `.env` ([.env.example](../.env.example) groups vars by build step).

## Target shape (M1 — the delegation slice)

M1 is the thinnest end-to-end path that crosses the Seam (ADR-0002):

```
Telegram ──▶ CommandClaw (Rust) ──MCP──▶ CKRV (ckrv-mcp) ──▶ verified diff ──▶ PR
   ▲                                                                            │
   └──────────────────────── PR URL ◀───────────────────────────────────────────┘
```

Build order — walking skeleton first, depth second ([plan/M1-delegation-slice.md](../plan/M1-delegation-slice.md)):

| Step | What | Built? |
|---|---|---|
| S0 | Rust workspace + CI (`cargo test` / `clippy`) | ✅ |
| S1 | Telegram echo (channel proven) | ✅ |
| S2 | One model call (model layer proven) | ✅ |
| S3 | `ckrv-mcp` reachable; `tools/list` returns CKRV's commands | ⬜ |
| S4 | Seam with a stub CKRV tool returning a fake PR URL | ⬜ |
| S5 | CKRV real, standalone: `ckrv run <spec>` → verified diff/PR (one provider, one sandbox) | ⬜ |
| S6 | Wire it: agent authors the Spec → delegates over MCP → real PR returns to chat = **M1 green** | ⬜ |

The skeleton (S1–S4) is deliberately shallow; the depth (S5–S6) is where CKRV's last 20% gets finished and real codegen lands. Until the round-trip closes once, the loop in `respond()` is the active build surface.

## The Seam (CommandClaw ↔ CKRV)

- CommandClaw is an **MCP client**; CKRV's `ckrv-mcp` is the **server**, exposing a run-spec tool that takes a *Spec* and returns `{verified, diff/PR url}`.
- **No code is shared across the Seam** (ADR-0001) — the two are independent products with independent release cycles. CKRV stays a pristine standalone CLI.
- CommandClaw builds its **own** model/provider layer ([model.rs](../crates/commandclaw/src/model.rs)) rather than reusing CKRV's `ckrv-model`.
- Transport mechanics are worked out in [plan/M1-delegation-slice.md](../plan/M1-delegation-slice.md) ("Seam mechanics") and are not yet wired (S4/S6).

## Deferred until M1 is green (the tripwire)

ADR-0002 forbids breadth before the round-trip closes. **None of the following exists, and none should be documented as if it does:** multi-channel, memory/Vault persistence, heartbeat/cron/autonomy, the Confirmation Gate, the skills system, a TUI, the phantom-token `commandclaw-mcp` proxy, multi-provider routing, and rich tracing/observability. M1 is deliberately **stateless and single-channel**.

One tenet is pre-decided for when memory lands (ADR-0003): agent state will be **version-controlled markdown** (the *Vault*) — edited directly by the human and audited via `git`, not held in chat or a database. It does **not** bind M1, which is stateless.

## Key files

- [crates/commandclaw/src/main.rs](../crates/commandclaw/src/main.rs) — Telegram channel + the `respond()` agent-loop seam (grow this).
- [crates/commandclaw/src/model.rs](../crates/commandclaw/src/model.rs) — `ModelClient`, the OpenAI-wire model layer.
- [Cargo.toml](../Cargo.toml) — workspace manifest; crates added per build step.
- [.env.example](../.env.example) — environment variables, grouped by build step.
- [docs/adr/0001-rebuild-commandclaw-rust.md](../docs/adr/0001-rebuild-commandclaw-rust.md) — why Rust, why a thin seam, why no shared code.
- [docs/adr/0002-m1-delegation-slice.md](../docs/adr/0002-m1-delegation-slice.md) — M1 and the tripwire.
- [docs/adr/0003-agent-state-version-controlled-markdown.md](../docs/adr/0003-agent-state-version-controlled-markdown.md) — the Vault tenet (post-M1).
- [CONTEXT.md](../CONTEXT.md) — glossary. [plan/M1-delegation-slice.md](../plan/M1-delegation-slice.md) — the build plan.
