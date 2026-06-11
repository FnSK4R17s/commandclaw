# M1 — The Delegation Slice (Build Plan)

> The first milestone of the CommandClaw rebuild. See `docs/adr/0001` (Rust rebuild + thin MCP seam) and `docs/adr/0002` (this milestone + the tripwire). Glossary in `CONTEXT.md`.
> Drafted 2026-06-11.

## Goal (one sentence)

A Telegram message asking for a code change comes back, minutes later, as a **pull-request link** — produced by CommandClaw writing a *Spec*, delegating it to CKRV over MCP, and CKRV turning that Spec into a **verified diff**.

## Definition of done (from ADR-0002 — do not expand)

`ckrv run <spec>` produces a verified diff/PR for **one** provider and **one** sandbox, invoked through `ckrv-mcp` **by CommandClaw**, triggered by a **Telegram** message, with the PR URL delivered back to the **same chat**. One successful round-trip = M1 green.

## The slice (what gets touched, nothing more)

```
Telegram ──▶ CommandClaw (Rust, greenfield) ──MCP──▶ CKRV (ckrv-mcp) ──▶ verified diff ──▶ PR
   ▲                                                                                        │
   └──────────────────────────── PR URL ◀───────────────────────────────────────────────────┘
```

Front half (CommandClaw-rust, new):
1. **Channel** — receive/send Telegram messages.
2. **Agent loop** — user message → model call → decide "this is a coding task" → author a *Spec* → call the delegate tool → get result → reply. Small but a *real* tool-calling loop (this is the learning prize — hand-roll it).
3. **Model layer** — one provider, OpenAI-wire-compatible.
4. **Spec authoring** — emit a minimal valid CKRV Spec (format per `ckrv-spec`).
5. **MCP client** — call CKRV's `ckrv-mcp` server; this *is* the seam.

Back half (CKRV, finish the last 20%):
6. **`ckrv-mcp` exposes a run-spec tool** that takes a Spec and returns `{verified, diff/PR url}`.
7. **`spec → plan → execute → verify → PR` works end-to-end** for ONE provider, ONE sandbox, on a toy target repo (`ckrv-integrations/github.rs` returns the PR URL).

## Build order — walking skeleton first, depth second

De-risk *integration* before *intelligence*. Get the round-trip working with stubs, then make each box real. Each step is independently runnable and verifiable.

- **S0 — Scaffold.** New Rust workspace on Windows (recommend a fresh `D:\apps\commandclaw-rs`, archive the Python tree; decision below). `cargo new`, hello-world binary, CI that runs `cargo test` + `cargo clippy`. ✅ when it builds green.
- **S1 — Telegram echo.** Bot receives a message, echoes it. (Channel proven.) ✅ when you DM it and it echoes.
- **S2 — One model call.** Message → LLM → reply. (Model layer proven.) ✅ when it answers a question over Telegram.
- **S3 — CKRV MCP up.** Run `ckrv-mcp` standalone; hit its trivial/list tool with any MCP client (inspector or curl). (CKRV reachable.) ✅ when a tool call returns.
- **S4 — Seam with a stub.** CommandClaw's MCP client calls a *stub* CKRV tool that returns a fake PR URL; agent relays it to Telegram. (Round-trip proven end-to-end, no real codegen yet.) ✅ when "do X" → fake PR link in chat.
- **S5 — CKRV real, standalone.** `ckrv run <hand-written-spec>` produces a real verified diff/PR on a toy repo, one provider, one sandbox — run from the CLI, no CommandClaw. (Backend done; CKRV's last 20% finished.) ✅ when a PR appears on the toy repo.
- **S6 — Wire it.** Replace the S4 stub with the S5 path: agent authors the Spec from the Telegram message, delegates via MCP, CKRV runs, real PR URL returns to chat. ✅ **= M1 green.**

The skeleton (S1–S4) is deliberately shallow; the depth (S5–S6) is where CKRV gets finished and the real codegen lands. If S5 stalls, M1 stalls honestly — that is the forcing function working.

## Non-goals (the tripwire — defer ALL of these until M1 is green)

Multi-channel; memory/vault persistence; heartbeat/cron/autonomy; the Confirmation Gate (M1 ends at a human-reviewed PR — inherently safe); skills system; TUI; the phantom-token `commandclaw-mcp` proxy; multi-provider routing; pretty tracing/observability. M1 may be **stateless and single-channel**. Breadth begins only after the round-trip closes once.

## Open decisions (settle at S0, don't pre-optimize)

- **Repo:** fresh `commandclaw-rs` (recommended — clean greenfield, archive Python) vs rebuild in-place. 
- **Agent-loop:** hand-roll the loop (recommended, it's the learning) but use `async-openai` for HTTP; consider `rig` only if hand-rolling stalls.
- **MCP Rust client/server:** pick the SDK (`rmcp` official, or `rust-mcp-sdk`). `ckrv-mcp` already exists server-side — match its protocol version.
- **Provider for M1:** dev on whatever's simplest (OpenAI-compatible). The AFK-friendly-provider question (Fireworks/Kimi, GLM) belongs to autonomy, which is post-M1 — do **not** solve it now.
- **Sandbox:** one only (`ckrv-sandbox`'s Docker path). Toy target repo with trivial CI.

## Seam note (Windows ↔ WSL)

CKRV currently lives on WSL; CommandClaw-rust builds on Windows. For M1 this is fine: run `ckrv-mcp` as a localhost server in WSL; the Windows MCP client reaches it over `localhost` (WSL2 forwards). If CKRV later moves to Windows, nothing in the slice changes — the seam is localhost MCP either way.

## What M1 proves

One green round-trip demonstrates, in miniature, the whole thesis: the agentic front (CommandClaw) and the deterministic back (CKRV) cooperating across a clean MCP seam to produce **human-reviewable, verified** code from a chat message. Everything after M1 — autonomy, memory, the safety gate, more channels — is breadth on a spine that already works.
