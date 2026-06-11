# 0001 — Rebuild CommandClaw from scratch in Rust as a standalone agent, delegating code changes to CKRV via MCP

- Status: Accepted
- Date: 2026-06-11
- Deciders: Shikhar Shukla (with grilling agent)

## Context

The Python CommandClaw is a thin, half-wired LangGraph shell (~3,021 LOC across 51 files; checkpointing imported but never wired; declared-but-unused deps; placeholder model id). It predates the author's AINE engineering experience and is considered slop.

CKRV (Chakravarti) is, by contrast, a well-structured Rust workspace (13 crates, ~87 test files, coherent DESIGN.md) — but it is a **deterministic spec→verified-diff pipeline with no agentic loop**. It is not an agent.

The two products previously overlapped ambiguously on "orchestration." The driver for this rebuild is **learning-first**: the author wants to understand agent internals deeply enough to anticipate the next technical frontier (as he did with orchestration in Dec 2025) and to build fast when he spots it.

## Decision

1. **Rebuild CommandClaw as a greenfield Rust project**, borrowing CKRV's conventions (RUST_CONVENTIONS.md, crate hygiene) and AINE learnings — **not** its code.
2. CommandClaw is the **agentic layer**; CKRV remains the **deterministic pipeline**. (CommandClaw decides what/whether; CKRV decides how/proves done.)
3. They are **separate products with a thin seam**: CommandClaw delegates a *Spec* to CKRV through **CKRV's MCP server** and receives a verified diff/PR.
4. **No code is shared** between them.

## Alternatives considered

- **Thin glue + study OpenClaw** (don't rebuild the runtime; learn by reading the canonical MIT implementation). Rejected: the author wants to learn by building, and a unified Rust stack is worth more than reading TS.
- **Adopt Claude Code / Codex headless as the brain.** Rejected: least learning; headless permission-prompt and observability pain (per the Dreams of Code CI-fixer source).
- **One Cargo workspace, share CKRV crates (`use ckrv_core`).** Rejected: quietly merges the two into one product, couples release cycles, and prevents CKRV shipping as a clean standalone OSS CLI.
- **Extract a shared `claw-model` crate** (fold commandclaw-gateway into ckrv-model). Rejected for now: keeps a code dependency across the seam; the author prefers full separation. (Revisit only if model-layer duplication becomes painful.)

## Consequences

**Positive**
- Unified Rust stack; the seam (the deliberate learning object) is Rust-to-Rust over MCP.
- CKRV stays a pristine standalone CLI honoring its DESIGN.md non-goals.
- Building the agent loop fresh maximizes learning of agent internals — the stated goal.
- The agent→deterministic-pipeline delegation seam is a candidate **next frontier** after orchestration.

**Negative / accepted costs**
- Rebuilds a commodity agent loop (the personal-agent whitepaper's "don't rebuild the commodity" caution). Accepted because the goal here is learning, not differentiation.
- CommandClaw builds its own model/provider layer rather than reusing `ckrv-model` — some duplication.
- The legacy Python `commandclaw-gateway` role is superseded by CommandClaw-rust's own model layer and should be retired or re-scoped.
- The Windows/WSL commandclaw branch divergence (`main` vs `feat/cat-mascot-sprite`) must be resolved before the rebuild starts.

## Open follow-ups (not decided here)

- Seam transport: CKRV's MCP server vs `ckrv run` CLI subprocess (leaning MCP, since `ckrv-mcp` already exists).
- CommandClaw-rust scope: which of the legacy 9 modules survive into the rebuild (thin-vs-fat).
- Fate of `commandclaw-gateway` and the phantom-token `commandclaw-mcp` (keep Python service vs Rust rewrite).
- Where the rebuild lives (in-place in this repo vs a fresh `commandclaw-rs`).

---

## Intent clarification (2026-06-11)

The "rebuilds a commodity agent loop" consequence above is **not** treated as a cost. The project's success criterion is **completion + learning** — the "Archon model": build the thing end-to-end as a passion project, philosophize and take notes while building, learn by doing. The grilling agent's earlier "napkin test / don't rebuild the commodity" pressure was product logic misapplied to a craft/learning project and is withdrawn.

- CKRV is built **end-to-end to working-as-planned**, but is **not** pursued as a GTM product. Its primary consumer is CommandClaw; the standalone CLI is preserved (honoring its DESIGN.md) but not actively marketed.
- CommandClaw likewise: built out fully, for use + learning, not as a product.
- Product / frontier monetization is an **option exercised later** if the build reveals it — not the goal of the build.

## Design constraint surfaced: AFK-friendly model providers

Anthropic's May 2026 HITL/AFK split made Claude Code uneconomical for unattended (AFK) work. Working hypothesis: other providers' subscription/unlimited plans still permit AFK/autonomous use (e.g. Fireworks Fire Pass → unlimited Kimi, as used in the Dreams of Code CI-fixer; Z.ai/GLM coding plans).

Constraint for both model layers (CKRV's `ckrv-model` and CommandClaw-rust's own): keep Anthropic for interactive/HITL, but route **autonomous/AFK** work to subscription-or-unlimited non-Anthropic providers. **Verify each provider's ToS permits unattended/automated use before relying on it.** (A dedicated ADR to follow once the provider strategy is finalized.)
