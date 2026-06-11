# CommandClaw — Context Glossary

> Canonical language for this codebase. Glossary only — no implementation detail.
> Maintained during grilling sessions. Last updated 2026-06-11.
> NOTE: a from-scratch Rust rebuild is underway (see docs/adr/0001). These terms describe the target system, not the legacy Python shell.

## Terms

**CommandClaw** — The **agent**: the conversational, autonomous, memory-bearing system the user talks to. It decides *what* to do and *whether* to act. Counterpart to *CKRV*, which decides *how* and proves *done*.

**Agentic Loop** — CommandClaw's open-ended cycle: receive input → assemble context → call model → call tools → (repeat) → respond. The defining property of CommandClaw, and what distinguishes it from CKRV's deterministic *Pipeline*.

**Channel** — A surface the agent is reached on (e.g. Telegram). One agent, many channels.

**Memory** — The agent's state persisted across sessions, held in the *Vault*. Distinct from a *Spec*: memory is who-the-agent-is and what-it-knows; a Spec is a one-off code-change contract handed across the *Seam*.

**Vault** — The version-controlled markdown files that hold the agent's *Memory* and configuration. The agent's **control plane**: edited directly by the human (not through chat) and audited via `git`. Distinct from a *Channel* (an I/O surface) and a *Spec* (a transient contract across the *Seam*). See `docs/adr/0003`.

**Heartbeat / Cron** — Autonomy triggers that make the agent act with no user message. Heartbeat applies judgment ("anything worth doing?"); Cron fires on a fixed schedule.

**Delegation** — When CommandClaw judges that a task requires deterministic code changes, it writes a *Spec* and hands it to CKRV across the *Seam*, then awaits a verified diff/PR. CommandClaw never edits code in an open-ended loop itself; it delegates that to the deterministic pipeline.

**Seam** — The thin boundary between CommandClaw (agent) and CKRV (pipeline). CommandClaw delegates a *Spec* via CKRV's MCP server and receives a verified diff/PR. **No code is shared across the Seam** — the two are independent products.

**Confirmation Gate** — The deterministic check that blocks irreversible or outward-facing actions unless pre-authorized. The safety primitive OpenClaw lacked (prose "standing orders" were insufficient); here it is code, not instruction.

## Relationship in one line

CommandClaw decides **what** and **whether** (agentic); CKRV decides **how** and proves **done** (deterministic).
