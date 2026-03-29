# Memory Architecture — Brainstorming

## The Problem We Skipped

CommandClaw's entire thesis is "vault is the control plane." But we never defined what memory actually looks like in practice. We have files (`MEMORY.md`, `memory/YYYY-MM-DD.md`) and vague instructions ("capture what matters"), but no architecture for:

1. **Conversation continuity** — how does the agent know what we just talked about?
2. **Memory lifecycle** — what gets saved, when, for how long?
3. **Memory hierarchy** — what's the relationship between short-term and long-term?
4. **Memory boundaries** — what's private, what's shared, what's session-scoped?

We assumed sensible defaults would emerge. They won't. This needs a deliberate design.

---

## What OpenClaw Does (and why it's insufficient)

OpenClaw uses **JSONL session files** — raw message dumps per conversation:

```
~/.openclaw/state/agents/{agentId}/sessions/{sessionId}.jsonl
```

Each file stores every message (user, assistant, tool calls, tool results) in order. On each turn, it loads the full history, truncates to a limit, and sends it all to the LLM.

**What works:**
- Full conversational continuity
- Resumable across restarts
- Per-channel isolation

**What's broken:**
- **Opaque** — JSONL is not human-readable or editable. You can't fix the agent's context.
- **Not versioned** — lives outside git, no audit trail, no rollback
- **Unbounded growth** — needs compaction/summarization heuristics that are fragile
- **No semantic structure** — it's a raw log, not organized knowledge
- **Leaks across concerns** — tool call internals mixed with meaningful conversation

---

## Questions We Need to Answer

### 1. What IS a conversation in CommandClaw?

Is it:
- A Telegram chat thread?
- A CLI session (between start and exit/Ctrl+C)?
- A calendar day?
- A task (defined by the user)?
- Something the agent decides?

OpenClaw ties it to the channel (`telegram:dm:123`). But CommandClaw's vault model suggests it should be **vault-scoped**, not channel-scoped. The agent is the same regardless of whether you talk to it via Telegram or CLI.

### 2. What does the agent need to remember between turns?

- The last few things said (conversational context)
- Decisions made in this session
- Tasks in progress
- Things the user explicitly said to remember
- Things the agent learned (corrections, preferences)

Not all of these have the same lifecycle or visibility requirements.

### 3. What SHOULDN'T persist?

- Tool call/result internals (the agent used bash to run `ls` — who cares?)
- Failed attempts and retries
- Intermediate reasoning
- Ephemeral coordination ("let me check that for you")

OpenClaw persists all of this. It shouldn't.

### 4. Who should control what's remembered?

- The agent? (writes what it thinks is important)
- The user? ("remember this", "forget that")
- The system? (automatic rules about retention)
- All three?

### 5. How does memory relate to git?

Options:
- **Everything committed** — full audit trail, but noisy git history
- **Working state uncommitted, summaries committed** — clean history, less auditable
- **Tiered** — hot state in uncommitted files, promoted to committed on session end

---

## Design Space

### Option A: Pure Vault (current design, extended)

Everything is markdown in the vault. No separate session store.

```
vault/
├── MEMORY.md                    # Curated long-term memory (committed)
├── memory/
│   ├── 2026-03-29.md           # Today's session log (committed on session end)
│   └── 2026-03-28.md           # Yesterday
```

**Conversation continuity**: Agent reads today's daily note + MEMORY.md at the start of each turn. Writes notable things to the daily note after each turn.

**Pros**: Simple, inspectable, editable, versioned, self-pruning by date.
**Cons**: No raw message history — agent sees its own summary, not the actual exchange. Lossy. "What did I say 3 messages ago?" may not work.

### Option B: Session Buffer + Vault Memory

Two tiers: a hot session buffer for conversation, vault for persisted knowledge.

```
vault/
├── MEMORY.md                    # Curated long-term (committed)
├── memory/
│   ├── 2026-03-29.md           # Daily log (committed)
│   └── 2026-03-28.md
├── .sessions/                   # Git-ignored, ephemeral
│   └── cli-20260329-143022.md  # Current session buffer (markdown, not JSONL)
```

The session buffer is **markdown** (not JSONL) — human-readable, editable. Contains actual conversation turns. Git-ignored because it's working state.

On session end (or daily rotation), the agent (or system) distills the session into the daily note — extracting decisions, learnings, and context.

**Pros**: Full conversational continuity AND clean vault. Best of both worlds.
**Cons**: Two systems to maintain. The distillation step could lose important nuance. Git-ignored means no audit trail for conversations.

### Option C: Structured Memory Graph

Memory as a graph of interconnected notes, not flat files.

```
vault/
├── MEMORY.md                    # Index / entrypoint
├── memory/
│   ├── topics/
│   │   ├── project-x.md        # Everything about project X
│   │   └── user-preferences.md # Learned preferences
│   ├── sessions/
│   │   ├── 2026-03-29-1430.md  # Session transcript (committed)
│   │   └── 2026-03-29-0900.md
│   └── insights/
│       ├── lesson-001.md       # Distilled learnings
│       └── decision-001.md     # Recorded decisions
```

Agent organizes memory into topics, sessions, and insights. Cross-references between them.

**Pros**: Richest model. Mirrors how humans actually remember things — by topic, not by date.
**Cons**: Complex. The agent has to be good at organization. Could become a mess. Hard to know what to load into context (can't read everything).

### Option D: Append-Only Log + Materialized Views

Inspired by event sourcing. Raw log is the source of truth, "views" are derived.

```
vault/
├── MEMORY.md                    # Materialized: curated summary (committed)
├── memory/
│   ├── log/                    # Append-only, committed
│   │   ├── 2026-03-29.jsonl    # Raw events: messages, decisions, tool uses
│   │   └── 2026-03-28.jsonl
│   └── views/                  # Derived, regeneratable
│       ├── recent-context.md   # Last N relevant interactions
│       ├── decisions.md        # All decisions extracted from log
│       └── preferences.md     # Learned user preferences
```

**Pros**: Lossless source of truth. Views can be rebuilt. Clean separation of raw data and interpretation.
**Cons**: JSONL in git is ugly. Views need a generation step. More infrastructure.

---

## Key Design Tensions

1. **Fidelity vs. Readability** — raw message history is complete but unreadable. Summarized memory is readable but lossy.

2. **Git-committed vs. Ephemeral** — committing everything creates a full audit trail but noisy git history. Ephemeral state is clean but unrecoverable.

3. **Agent-managed vs. User-managed** — if the agent decides what to remember, it might miss things or remember wrong. If the user manages it, it's tedious.

4. **Context window vs. Memory depth** — more memory = more context tokens = less room for actual work. There's a hard ceiling.

5. **Privacy boundaries** — in group chats, the agent shouldn't leak private conversation context. Memory needs access control.

---

## Open Questions

- Should session transcripts be committed to git or git-ignored?
- How much of the context window should memory consume? (10%? 25%? 50%?)
- Should the agent actively manage its own memory, or should it be system-automated?
- How do we handle the "remember this" vs "this is just conversation" distinction?
- What's the right unit of memory — a message? a turn? a topic? a session?
- How does memory work in multi-agent setups (week two)?

---

## Cost Analysis — Embedding Everything

**Conclusion: cost is a non-issue.** We can afford to embed every message.

### OpenAI text-embedding-3-small ($0.02/1M tokens)

| Usage | Tokens/day | Cost/year |
|-------|-----------|-----------|
| Light (10 msgs) | ~5K | $0.04 |
| Power user (500 msgs) | ~250K | $1.83 |
| Insane (10K msgs, multi-agent) | ~5M | $36.50 |

### Local models (free)

- `nomic-embed-text-v2` via Ollama — best accuracy (~86%), ~275MB
- `all-MiniLM-L6-v2` — fastest (14.7ms/1K tokens), ~80MB
- `BGE-base-v1.5` — good balance, ~440MB

### Cost context

With Codex OAuth subscription accounts, LLM calls are covered by the ChatGPT subscription. Embedding costs are a rounding error even on OpenAI's API. **There is no cost constraint on memory — the design should optimize for quality, not savings.**

---

## Prior Art Worth Studying

### OpenViking (volcengine)
- Filesystem-as-hierarchy for context — very aligned with vault model
- Three-tier loading (L0/L1/L2) to manage context window budget
- Automatic session compression → long-term memory extraction
- Combines directory positioning with semantic search

### qmd (tobi)
- Local-first, SQLite-backed
- Hybrid search: BM25 (keyword) + vector (semantic) + LLM reranking
- Context hierarchy — metadata annotations returned alongside matched documents
- Runs entirely on-device, no cloud dependency

---

## What I'm Leaning Toward

(To be filled in after thinking)
