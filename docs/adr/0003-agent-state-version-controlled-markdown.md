# 0003 — Agent state is version-controlled markdown (inherited tenet)

- Status: Accepted
- Date: 2026-06-11
- Deciders: Shikhar Shukla (with grilling agent)

## Context

The Python CommandClaw and its enterprise vision (`guiding_docs/VISION.md`) are superseded by the greenfield Rust rebuild (ADR-0001). Before discarding the old vision, we culled it for ideas worth keeping. Most are dead (enterprise positioning, the LangChain/OpenAI stack) or deferred (skills, Langfuse, RBAC, multi-agent — see ADR-0002's tripwire).

One storage tenet survives and is strong enough to bind the rebuild. It is the old vision's answer to two specific OpenClaw failures:

- **Opaque, chat-only state.** Agents forgot configuration, credentials, and instructions; the only way to inspect or change agent state was to ask the agent in chat.
- **No record of what changed.** State mutated invisibly — no audit of when or why.

Because the rebuild is greenfield, a future reader could reasonably assume the old philosophy died with the old code. This ADR records that it did not: one tenet was deliberately preserved across the cull and now constrains the rebuild.

## Decision

Agent state — memory, configuration, behavior — lives as **version-controlled markdown files** (the *Vault*). Two clauses:

1. **Markdown, not JSON or other structured formats.** Agents corrupt structured formats; markdown is forgiving and nearly impossible to break beyond usability.
2. **Files, not chat or a database.** The human reads and edits the Vault directly. This rules out chat-as-configuration and a database-backed memory store.

## Consequences

**Positive**

- `git log` / `git diff` over the Vault is the complete audit trail — every state change is versioned, traceable, attributable.
- Git-based recovery: on a bad write, discard uncommitted changes and resume from the last good commit. No bespoke checkpointing.
- The human corrects the agent by editing a file, not by negotiating with it in chat.

**Scope / accepted**

- **M1 is stateless** (ADR-0002). There is no Vault yet. This tenet binds the **memory layer when it lands**, post-M1 — it does not constrain M1.
- The **Confirmation Gate** (safety on irreversible actions) is a **new** invention, not inherited from this vision. It gets its own ADR and is out of scope here.
- Markdown-only is scoped to **agent-written persistent state** (the Vault). It does **not** govern the CKRV *Spec* — a machine-generated, validated contract across the Seam whose format is CKRV's concern.

## Considered alternative

**Blank-slate the philosophy too.** Since the rebuild throws out all the old code, re-derive the storage model from scratch rather than inheriting anything. Rejected: the two OpenClaw failures above are real and the markdown-files-in-git answer is proven; re-deriving it would discard a learned lesson for no benefit.
