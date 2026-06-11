# 0002 — First milestone is the delegation slice (M1); no CommandClaw breadth before it

- Status: Accepted
- Date: 2026-06-11
- Deciders: Shikhar Shukla (with grilling agent)

## Context

Sequencing decision following ADR-0001. The author chose to **start with CommandClaw-rust** (richest learning right now: the agentic loop is the 2026-relevant skill; CKRV's orchestration is a solved last-year problem) while building **both** products.

The risk is documented in the author's own vibe-coding practice audit: a historical pattern of *starting many projects and finishing none*. Greenfield Rust CommandClaw is high-dopamine and could sprawl into channels/memory/skills while CKRV stalls at ~80%. **Completion** is the stated success criterion (ADR-0001), so the sequence must enforce completion **structurally**, not by willpower.

## Decision

1. **M1 (first milestone)** is the thinnest end-to-end path that crosses the seam:
   > Telegram message → CommandClaw agent loop → it writes a *Spec* → delegates to CKRV over MCP (`ckrv-mcp`) → CKRV runs `spec → verified diff` → PR link returns to the same Telegram chat.
2. **M1 forces CKRV to done.** M1 cannot be reached without CKRV's `spec → verified diff` path working end-to-end. CKRV completion is therefore a *forced dependency* of M1, not a separate effort that can be deferred.
3. **Tripwire:** until M1 is green, CommandClaw gains **nothing** beyond what M1 requires — agent loop + one channel (Telegram) + one model provider + spec authoring + MCP delegation. Explicitly deferred until *after* M1: multi-channel, skills system, heartbeat/cron, TUI, rich tracing, and the phantom-token `commandclaw-mcp` proxy.

## Consequences

**Positive**
- Completion enforced by the milestone's dependency graph, not by discipline alone — the direct corrective to the audit's finding.
- The **seam** (the key learning object and candidate next-frontier) is built first, not last.
- One milestone advances learning, completion, and the seam simultaneously.
- CKRV is finished as M1's backend, giving CommandClaw a stable delegation target.

**Negative / accepted**
- CommandClaw stays deliberately crippled (single-channel, no autonomy) until M1 closes; "personal agent" breadth is postponed.
- If M1 stalls, both products stall together — accepted: a stalled M1 is honest signal, whereas parallel half-builds hide the stall.

## Definition of done (M1)

`ckrv run <spec>` produces a verified diff/PR for **at least one** provider and **one** sandbox, invoked through `ckrv-mcp` by CommandClaw, triggered by a Telegram message, with the PR URL delivered back to the same chat. When this round-trips once, M1 is green and breadth may begin.
