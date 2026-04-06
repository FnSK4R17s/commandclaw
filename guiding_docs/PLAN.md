# PLAN.md — Memory Layer Implementation

**Status:** DRAFT — awaiting signoff before implementation begins.
**Date:** 2026-04-06
**Supersedes:** [archive/PLAN-2026-04-06.md](archive/PLAN-2026-04-06.md)

This plan defines exactly what to build to give CommandClaw a proper memory layer, based on the synthesis of two independent design inputs:

- **[MEMORY_PRD_KARPATHY.md](MEMORY_PRD_KARPATHY.md)** — Andrej Karpathy's LLM Wiki pattern. Defines the *data model* and *workflow contract*: markdown wiki the LLM maintains, `index.md` as a content catalog, `log.md` as a chronological audit, ingest/query/lint operations.
- **[whitepaper-output/commandclaw-memory-service/](../whitepaper-output/commandclaw-memory-service/whitepaper/commandclaw-memory-service-whitepaper.md)** — BEARY whitepaper. Defines the *infrastructure*: FastAPI microservice, LanceDB + BM25 hybrid retrieval, Cerbos RBAC, HMAC auth, distillation worker, git-first sync.

These are not alternatives. They are complementary layers:

| Layer | Source | Job |
|---|---|---|
| **Data model + workflow** | Karpathy PRD | What lives in the vault, how it's structured, the contract between human and agent |
| **Infrastructure + enforcement** | BEARY whitepaper | How the data is stored, indexed, retrieved, validated, secured, and distilled |

The design principle underneath both: **CommandClaw is built for enterprise reliability, which means it must work with cheap or weak models, not only with frontier Claude models.** A cheap model cannot be trusted to self-maintain a wiki the way Karpathy's workflow assumes. The memory service is the discipline layer that enforces the schema the LLM is supposed to follow — so that when the LLM gets it wrong, the service rejects the write instead of corrupting the knowledge base.

---

## Table of Contents

1. [Scope and non-scope](#1-scope-and-non-scope)
2. [Architecture overview](#2-architecture-overview)
3. [Vault layout — the wiki schema](#3-vault-layout--the-wiki-schema)
4. [The memory service — `commandclaw-memory`](#4-the-memory-service--commandclaw-memory)
5. [Schema enforcement](#5-schema-enforcement)
6. [Distillation pipeline](#6-distillation-pipeline)
7. [Agent integration](#7-agent-integration)
8. [Auth, tenancy, and RBAC](#8-auth-tenancy-and-rbac)
9. [Failure modes and graceful degradation](#9-failure-modes-and-graceful-degradation)
10. [Migration plan](#10-migration-plan)
11. [Observability and ops](#11-observability-and-ops)
12. [Build phasing](#12-build-phasing)
13. [Open questions](#13-open-questions)
14. [What this plan does not cover](#14-what-this-plan-does-not-cover)

---

## 1. Scope and non-scope

### In scope

- New vault directory structure (`wiki/` subtree) with Karpathy-style page types, `index.md`, `log.md`
- New repository `commandclaw-memory` — FastAPI microservice, LanceDB store, Tantivy BM25 index, distillation worker, Cerbos integration
- New `MemoryServiceStore` class in `commandclaw` implementing LangGraph `BaseStore` interface
- Schema enforcement on wiki writes (Pydantic models, frontmatter validation)
- Distillation worker (configurable model, background asyncio task)
- Auth consistent with `commandclaw-mcp` (phantom token + HMAC + Cerbos)
- Migration script to bootstrap the memory service from an existing vault
- AGENTS.md section documenting the ingest/query/lint workflow for agents
- Updates to `commandclaw-vault` template to seed a fresh agent with `wiki/index.md` and `wiki/log.md`
- Docker compose integration alongside existing `commandclaw-mcp`

### Out of scope for this plan

- Multi-machine deployment (single-machine is the target)
- Kubernetes, cloud orchestration
- Replacing the existing `commandclaw-mcp` gateway
- Changing the LangGraph runtime, NeMo Guardrails, or Langfuse integration
- Embedding model changes (`BGE-small-en-v1.5` for hot-path retrieval, pre-cached)
- Scheduler/cron (separate concern — belongs in a future plan)
- Telegram runtime port to LangGraph (tracked separately as a gap)
- Any work on `commandclaw-skills`, `commandclaw-observe`, or `commandclaw-vault` beyond template additions for `wiki/`

### Explicitly preserved

- The `memory/YYYY-MM-DD.md` daily notes directory stays. It becomes a *raw source* that feeds the wiki via distillation. The wiki is additive; daily notes are not deprecated.
- `MEMORY.md` stays as the hot-tier file loaded into the system prompt on every invocation. Its role does not change.
- The git vault remains the source of truth. LanceDB is always derivable from it.

---

## 2. Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Per-agent container (one per agent)                            │
│                                                                 │
│  LangGraph runtime                                              │
│    ├─ Native tools (bash, file_*, memory_*, skill_*)            │
│    ├─ MemoryServiceStore (BaseStore shim)    ───────┐           │
│    └─ MCP tools (via commandclaw-mcp)    ────────┐  │           │
│                                                   │  │           │
└───────────────────────────────────────────────────┼──┼───────────┘
                                                    │  │
                           HTTP (loopback)          │  │
                     port 8283  ◄──────────────────┘  │
                     port 8284  ◄─────────────────────┘
                                                    │  │
                     ┌──────────────┐    ┌──────────▼──▼──────┐
                     │ commandclaw- │    │ commandclaw-memory │
                     │     mcp      │    │     (new)          │
                     │  (existing)  │    │                    │
                     │              │    │  FastAPI           │
                     │  Tools RBAC  │    │  LanceDB (warm)    │
                     │  Credential  │    │  Tantivy (BM25)    │
                     │  injection   │    │  Schema validator  │
                     └──────┬───────┘    │  Distill worker    │
                            │            │  Cerbos client     │
                            │            └──────┬─────────────┘
                            │                   │
                            │  git commit (synchronous)
                            │                   │
                            ▼                   ▼
                     ┌──────────────────────────────────────┐
                     │  commandclaw-vault (git)             │
                     │                                      │
                     │  MEMORY.md          ← hot tier       │
                     │  memory/*.md        ← daily notes    │
                     │  wiki/              ← NEW            │
                     │    index.md                          │
                     │    log.md                            │
                     │    sources/                          │
                     │    entities/                         │
                     │    concepts/                         │
                     │    syntheses/                        │
                     │  IDENTITY.md, AGENTS.md, USER.md     │
                     └──────────────────────────────────────┘
```

Key invariants:

1. **Git vault is the source of truth.** LanceDB and BM25 are always rebuildable from it.
2. **Writes are synchronous to git, async to the index.** Git commit completes before the HTTP response returns. Index updates are eventual.
3. **The memory service is the sole writer to LanceDB.** No agent process touches LanceDB directly.
4. **Agent code uses the `BaseStore` shim.** It doesn't import LanceDB, doesn't know the port, doesn't construct HTTP clients directly.
5. **Schema enforcement is at the service boundary.** Any markdown that enters `wiki/` does so through a validated REST endpoint, not direct file writes.
6. **Hot path never waits on distillation.** Distillation is a background worker. Agent writes and reads do not block on it.

---

## 3. Vault layout — the wiki schema

The wiki lives at `vault/wiki/` and is structured according to Karpathy's pattern, refined for enterprise discipline.

### 3.1 Directory layout

```
wiki/
├── index.md                  # Content catalog (service-maintained)
├── log.md                    # Append-only audit log (service-maintained)
├── sources/                  # One page per ingested raw source
│   └── <slug>.md
├── entities/                 # Per-entity pages (people, projects, tools, places)
│   └── <slug>.md
├── concepts/                 # Per-concept pages (abstract topics, principles)
│   └── <slug>.md
└── syntheses/                # Cross-cutting synthesis pages (LLM-generated analyses)
    └── <slug>.md
```

### 3.2 Page types and frontmatter

Every wiki page has YAML frontmatter. The memory service validates frontmatter on every write.

**Source page (`sources/<slug>.md`)**

```yaml
---
type: source
slug: karpathy-llm-wiki
title: "Karpathy — LLM Wiki pattern"
source_url: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
ingested_at: 2026-04-06T14:22:00Z
ingested_by: beary
tags: [memory, architecture, wiki-pattern]
entities: [karpathy, obsidian]
concepts: [llm-wiki, ingest-query-lint]
supersedes: []
superseded_by: null
---
```

Body is a structured summary written by the ingestion flow. Must include a "Key claims" section and a "Connections" section listing related pages.

**Entity page (`entities/<slug>.md`)**

```yaml
---
type: entity
slug: karpathy
name: "Andrej Karpathy"
kind: person
first_seen: 2026-04-06T14:22:00Z
last_updated: 2026-04-06T14:22:00Z
sources: [sources/karpathy-llm-wiki]
related_entities: []
related_concepts: [llm-wiki]
---
```

**Concept page (`concepts/<slug>.md`)**

```yaml
---
type: concept
slug: llm-wiki
name: "LLM Wiki"
first_seen: 2026-04-06T14:22:00Z
last_updated: 2026-04-06T14:22:00Z
sources: [sources/karpathy-llm-wiki]
related_concepts: [ingest-query-lint, memex]
related_entities: [karpathy]
---
```

**Synthesis page (`syntheses/<slug>.md`)**

```yaml
---
type: synthesis
slug: memory-layer-decision
title: "Memory layer: wiki pattern + service infrastructure"
created_at: 2026-04-06T16:00:00Z
author: main-assistant
sources: [sources/karpathy-llm-wiki, sources/beary-memory-whitepaper]
entities: []
concepts: [llm-wiki, memory-service, cheap-model-safety]
confidence: high
---
```

### 3.3 index.md — the content catalog

`wiki/index.md` is the service-maintained catalog. It is not editable by hand; the memory service rewrites it on every successful write. Format:

```markdown
# Wiki Index

Last updated: 2026-04-06T16:00:00Z by memory-service

## Sources (2)

- [karpathy-llm-wiki](sources/karpathy-llm-wiki.md) — Karpathy's LLM Wiki pattern (2026-04-06)
- [beary-memory-whitepaper](sources/beary-memory-whitepaper.md) — BEARY memory service architecture (2026-04-06)

## Entities (1)

- [karpathy](entities/karpathy.md) — Andrej Karpathy (person)

## Concepts (3)

- [llm-wiki](concepts/llm-wiki.md) — LLM Wiki pattern
- [ingest-query-lint](concepts/ingest-query-lint.md) — The three wiki operations
- [memex](concepts/memex.md) — Vannevar Bush's Memex

## Syntheses (1)

- [memory-layer-decision](syntheses/memory-layer-decision.md) — Memory layer: wiki pattern + service infrastructure
```

The index exists so an agent (including a cheap model) can discover what's in the wiki without loading every page. It's a flat catalog, not a hierarchy.

### 3.4 log.md — the audit log

`wiki/log.md` is append-only. Every ingest, query (optional), lint pass, and distillation run appends an entry. Format:

```markdown
## [2026-04-06T14:22:00Z] ingest | karpathy-llm-wiki

Ingested by: beary
Touched pages:
- sources/karpathy-llm-wiki.md (created)
- entities/karpathy.md (created)
- concepts/llm-wiki.md (created)
- concepts/ingest-query-lint.md (created)
- concepts/memex.md (created)
- index.md (updated)

## [2026-04-06T16:00:00Z] synthesis | memory-layer-decision

Created by: main-assistant
Inputs: sources/karpathy-llm-wiki, sources/beary-memory-whitepaper
Output: syntheses/memory-layer-decision.md
```

Entries are parseable via simple unix tools (`grep "^## \[" log.md | tail -20`).

---

## 4. The memory service — `commandclaw-memory`

A new git repository and Python package: `commandclaw-memory`.

### 4.1 Repository layout

```
commandclaw-memory/
├── pyproject.toml
├── README.md
├── Dockerfile
├── docker-compose.yml
├── src/commandclaw_memory/
│   ├── __init__.py
│   ├── __main__.py              # Entry point (uvicorn + distill worker)
│   ├── config.py                # Pydantic Settings
│   ├── service/
│   │   ├── app.py               # FastAPI app factory
│   │   ├── auth.py              # Phantom token + HMAC
│   │   ├── middleware.py        # Logging, tracing, auth middleware
│   │   └── endpoints/
│   │       ├── wiki.py          # Wiki CRUD
│   │       ├── search.py        # Hybrid search
│   │       ├── ingest.py        # Source ingestion trigger
│   │       ├── lint.py          # Health check trigger
│   │       ├── admin.py         # Reindex, stats
│   │       └── health.py        # Liveness/readiness
│   ├── storage/
│   │   ├── lancedb_store.py     # LanceDB writer/reader
│   │   ├── bm25_store.py        # Tantivy BM25 index
│   │   └── vault_writer.py      # Git commit + schema validation
│   ├── schema/
│   │   ├── models.py            # Pydantic models per page type
│   │   ├── validators.py        # Cross-reference validation
│   │   └── frontmatter.py       # YAML parse/serialize
│   ├── distill/
│   │   ├── worker.py            # Background asyncio task
│   │   ├── queue.py             # Append-only JSONL queue
│   │   ├── extractors.py        # Fact extraction (rule + LLM)
│   │   └── prompts.py           # LLM prompts for extraction/summarization
│   ├── rbac/
│   │   └── cerbos_client.py
│   └── index/
│       ├── index_writer.py      # Rewrites wiki/index.md
│       └── log_writer.py        # Appends to wiki/log.md
└── tests/
    ├── test_schema.py
    ├── test_wiki_crud.py
    ├── test_search.py
    ├── test_distill.py
    └── test_migration.py
```

### 4.2 REST API

All endpoints authenticated via phantom token + HMAC. All responses are JSON.

**Wiki CRUD**

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/wiki/pages` | Create a new page. Validates schema. Commits to git. Updates index. Enqueues for indexing. |
| `GET` | `/wiki/pages/{type}/{slug}` | Read a page by type and slug. |
| `PATCH` | `/wiki/pages/{type}/{slug}` | Update an existing page. Validates schema. Commits to git. Updates index. Enqueues reindex. |
| `DELETE` | `/wiki/pages/{type}/{slug}` | Delete a page. Only permitted by admin or original author. |

**Search**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/wiki/search` | Hybrid BM25 + vector + RRF fusion. Supports `query`, `type`, `namespace`, `limit`, `mode={hybrid,vector,bm25,index}`. |
| `GET` | `/wiki/index` | Returns a structured representation of `index.md` as JSON. |

**Ingest and distillation**

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/ingest/source` | Triggers ingestion of a raw source (URL, text, or path to file in vault). Returns a job ID. |
| `POST` | `/distill/session` | Triggers distillation of a session transcript. Returns a job ID. |
| `GET` | `/jobs/{job_id}` | Poll job status. |
| `POST` | `/lint` | Triggers wiki lint pass (contradictions, orphans, stale claims, missing pages). Returns a report. |

**Admin**

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/admin/reindex` | Full rebuild of LanceDB and BM25 from vault. Admin only. |
| `GET` | `/admin/stats` | Page counts, search latency percentiles, queue depths. |
| `POST` | `/admin/enroll` | Register a new agent principal (agent_id + token + hmac_key). |

**Operational**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness. Cheap. |
| `GET` | `/ready` | Readiness. Checks LanceDB, Tantivy, git vault, Cerbos. |
| `GET` | `/metrics` | Prometheus-compatible metrics. |

### 4.3 Data flow on a wiki page write

1. Agent calls `POST /wiki/pages` via the `MemoryServiceStore` shim
2. Auth middleware verifies phantom token + HMAC signature
3. Cerbos middleware checks `principal={agent_id, role}` can write this page type in this namespace
4. Schema validator parses the body as the appropriate Pydantic model for the page type
5. Cross-reference validator checks that all `sources`, `entities`, `concepts` listed in frontmatter actually exist (or are being created atomically in the same request)
6. `vault_writer` writes the markdown file to the git vault and commits synchronously
7. `index_writer` rewrites `wiki/index.md` to include the new page; same git commit
8. `log_writer` appends to `wiki/log.md`; same git commit
9. `lancedb_store.enqueue(page)` — async, returns immediately
10. `bm25_store.enqueue(page)` — async, returns immediately
11. Response returned to agent: `{page_id, path, git_commit_sha}`

The entire write is one git commit with three files touched: the page itself, the updated `index.md`, the updated `log.md`. The index update is not a separate commit so a failure can't leave `index.md` out of sync.

### 4.4 Data flow on a search

1. Agent calls `GET /wiki/search?query=...&mode=hybrid` via shim
2. Auth + Cerbos checks
3. `search` endpoint dispatches to BM25 and LanceDB in parallel
4. Results fused via reciprocal rank fusion
5. Cerbos filters results by namespace visibility
6. Response returned to agent with `{results, search_latency_ms}`

Latency target: sub-60ms on loopback at 100K pages.

---

## 5. Schema enforcement

The memory service is the only writer. Agents *never* write markdown to `wiki/` directly via `file_write`. This is enforced at two levels:

1. **Convention**: the agent's AGENTS.md explicitly forbids writing to `wiki/` with native file tools. The agent must use the wiki tools (see section 7).
2. **Tooling**: the native `file_write` tool rejects paths under `wiki/` with a clear error message pointing the agent at the wiki tools.

The memory service validates every write via Pydantic models (`schema/models.py`), one per page type. A write fails if:

- Frontmatter is malformed
- Required fields are missing
- `type` doesn't match the path (`sources/` must have `type: source`)
- `slug` doesn't match the filename
- Referenced sources/entities/concepts don't exist
- Content is empty or shorter than a minimum length
- The page would create a circular `supersedes` chain

Why this matters for enterprise: a cheap model will occasionally generate malformed frontmatter, skip required fields, or invent slugs for entities that don't exist. Without enforcement, the wiki rots silently. With enforcement, the service returns `422 Unprocessable Entity` and the agent has to fix its output — the wiki stays consistent regardless of which model is driving.

---

## 6. Distillation pipeline

Distillation is the background process that converts raw inputs (session transcripts, daily notes, ingested sources) into structured wiki pages.

### 6.1 What distillation does

Given a raw input, distillation produces:

- A source page if one doesn't exist
- New or updated entity pages for people, tools, projects mentioned
- New or updated concept pages for abstract topics
- Optionally, a new synthesis page if the input contains cross-cutting analysis

### 6.2 Why it's async and background

- **Hot path protection**: agents never wait on distillation during a session. The write returns immediately, distillation happens later.
- **Cost control**: distillation uses a stronger (more expensive) model — gpt-4o-mini or similar — off the critical path. The primary agent can use a cheaper model.
- **Quality**: the distillation worker can take its time, do multiple passes, and cross-check against existing wiki content before writing.

### 6.3 Trigger points

- Session end: agent calls `POST /distill/session` with the session transcript
- Daily note append: a git post-commit hook on the vault enqueues any modified `memory/*.md` file
- Manual ingest: user or agent calls `POST /ingest/source` with a URL or text
- Lint pass: `POST /lint` may discover a missing page and enqueue a distillation to create it

### 6.4 Worker design

A separate asyncio task inside the memory service process reads from an append-only JSONL queue (`queue/pending.jsonl`). For each job:

1. Pull job from queue
2. Load inputs (source text, existing wiki pages that may be affected)
3. Call LLM with an extraction prompt (`distill/prompts.py`)
4. Parse structured output (Pydantic validation)
5. For each produced page, call the internal wiki write path (same schema validation as external writes)
6. Mark job complete
7. If failure: retry up to 3 times, then move to `queue/dead.jsonl` for manual review

The worker is single-threaded per service instance. Multiple concurrent jobs are not needed at single-machine scale and would complicate write ordering.

### 6.5 Model selection

The distillation model is configurable via environment variable:

```
COMMANDCLAW_MEMORY_DISTILL_MODEL=gpt-4o-mini
COMMANDCLAW_MEMORY_DISTILL_API_KEY=...
```

Default is `gpt-4o-mini` for cost reasons. A rule-based fallback mode (`COMMANDCLAW_MEMORY_DISTILL_MODEL=rule-based`) is available for fully offline operation or when no LLM is available — it extracts entities and concepts by regex and heading patterns only. Quality is lower but deterministic and free.

---

## 7. Agent integration

### 7.1 `MemoryServiceStore` — BaseStore shim

A new class in `commandclaw/src/commandclaw/memory/service_store.py` that implements LangGraph's `BaseStore` interface:

```python
class MemoryServiceStore(BaseStore):
    def __init__(self, base_url: str, agent_id: str, token: str, hmac_key: str): ...
    async def asearch(self, namespace, query, limit=10): ...
    async def aput(self, namespace, key, value): ...
    async def aget(self, namespace, key): ...
    async def adelete(self, namespace, key): ...
```

The shim translates LangGraph's tuple-based namespace convention to the REST API's path scheme. Agent code does not know the memory service exists.

### 7.2 New agent tools

Four new native tools in `commandclaw/src/commandclaw/agent/tools/wiki_*.py`:

| Tool | Purpose |
|---|---|
| `wiki_search` | Search the wiki. Returns top-K results with paths and snippets. |
| `wiki_read` | Read a specific wiki page by type and slug. |
| `wiki_ingest` | Ingest a raw source (URL, text, or path). Returns a job ID and polls until complete or timeout. |
| `wiki_lint` | Trigger a lint pass. Returns the report. |

The agent never writes wiki pages directly via a tool. Writes happen only via:

1. `wiki_ingest` → distillation worker writes pages based on the raw source
2. The distillation worker running on session end (invoked by the runtime, not the agent directly)

This enforces the principle that the wiki is LLM-maintained but through a disciplined workflow, not raw markdown authoring.

### 7.3 AGENTS.md additions

A new section in the vault's `AGENTS.md` template teaches the agent:

- What the wiki is, what lives in it
- How to query it via `wiki_search` and `wiki_read`
- How to ingest a new source via `wiki_ingest`
- Not to write markdown to `wiki/` via `file_write`
- When to run `wiki_lint`
- How distillation works so the agent doesn't duplicate what the worker does automatically

This replaces any existing "memory" section.

### 7.4 Runtime wiring

In `commandclaw/src/commandclaw/agent/graph.py`:

- Add `MemoryServiceStore` construction alongside the existing MCP client
- Pass it to the LangGraph `StateGraph` as the `store` parameter
- Add the four wiki tools to the native tools list
- On graceful degradation (service unavailable): the shim returns empty results for search and buffers writes to a local JSONL file (same pattern as `commandclaw-mcp` fallback)

---

## 8. Auth, tenancy, and RBAC

### 8.1 Auth

Identical pattern to `commandclaw-mcp`:

- **Phantom token**: opaque, rotated hourly, issued by the memory service at agent enrollment (`POST /admin/enroll`)
- **HMAC-SHA256 request signing**: every request signed over `METHOD + PATH + TIMESTAMP + NONCE + SHA256(BODY)`
- **Nonce cache**: Redis-backed, 5 minute TTL, prevents replay
- **Development mode**: `COMMANDCLAW_MEMORY_AUTH_DISABLED=true` bypasses checks for local dev only

Credentials (`token`, `hmac_key`) are passed to the agent container via the same env-file mechanism used by `commandclaw-mcp`.

### 8.2 Tenancy

Every page has an `agent_id` in frontmatter. Namespaces:

```
private/<agent_id>/   # Default namespace for pages created by this agent
shared/               # Cross-agent readable
  research/           # For research outputs (written by any agent, read by all)
  decisions/          # For project decisions
  reference/          # For static reference content
admin/                # Admin-only, for system-level content
```

By default, an agent writes to `private/<agent_id>/` and can read from `private/<agent_id>/` + `shared/`. Promotion to `shared/` requires an explicit `namespace` parameter in the write request, subject to Cerbos policy.

### 8.3 RBAC via Cerbos

Existing Cerbos instance is reused. New policy file: `commandclaw-mcp/policies/memory_service.yaml` (or a separate instance at the memory service level). Example rules:

- `beary` can write to `private/beary/` and `shared/research/`, can read `private/beary/` and `shared/`
- `main-assistant` can write to `private/main-assistant/` and `shared/decisions/`, can read `private/main-assistant/` and `shared/`
- `admin` can do anything
- `reader` (future) can read `shared/` only, cannot write

Cerbos policy check happens on every request. Denies return `403 Forbidden` with a reason.

---

## 9. Failure modes and graceful degradation

The memory service is not on the critical path for agent *responsiveness* — the agent can still operate with only `MEMORY.md` hot-tier context. But it *is* on the critical path for *memory continuity*.

### 9.1 Degradation sequence

1. **Health check at agent startup**: the runtime pings `GET /health`. On failure, construct a `DegradedMemoryServiceStore` that serves empty results and buffers writes to `~/.commandclaw/memory/queue/offline_writes.jsonl`.
2. **Per-request circuit breaker**: if a request to the memory service fails, open the breaker for 30 seconds. During open state, all operations use the degraded path.
3. **Runtime notice**: a system message is appended to the agent's prompt: `"Memory service unavailable. Operating on hot-tier context only. Wiki tools will return empty results."`
4. **Replay on recovery**: when the service comes back, the runtime replays `offline_writes.jsonl` in order and clears it.

### 9.2 Specific failure paths

| Failure | Behavior |
|---|---|
| Memory service is down | Degraded mode, system prompt notice |
| LanceDB index is corrupted | Service returns 503 on search; lint and ingest still work; trigger `/admin/reindex` |
| Cerbos is unreachable | Deny-by-default (fail closed); agent cannot write until Cerbos returns |
| Distillation worker is dead | Writes still succeed; distill queue backs up; `/admin/stats` surfaces the backlog |
| Git commit fails | HTTP response returns 500; write is atomic (either committed or rolled back) |
| Schema validation fails | HTTP 422 with detailed error; no side effects |

### 9.3 What we explicitly do not do

- **No silent drops**: if a write fails, the agent is told. No writes are ever acknowledged without the git commit completing.
- **No partial index updates**: if LanceDB indexing fails after a successful git commit, the next `/admin/reindex` will catch it. The source of truth remains consistent.

---

## 10. Migration plan

An existing CommandClaw vault has `MEMORY.md` and `memory/*.md` but no `wiki/`. The migration seeds the wiki and the index from existing vault content.

### 10.1 One-shot migration script

Location: `commandclaw-memory/src/commandclaw_memory/migrate/bootstrap.py`

Run with: `python -m commandclaw_memory.migrate bootstrap --vault /path/to/vault`

Steps:

1. Create `wiki/`, `wiki/sources/`, `wiki/entities/`, `wiki/concepts/`, `wiki/syntheses/` if missing
2. Create empty `wiki/index.md` and `wiki/log.md` if missing
3. For each file in `memory/*.md`:
   - Create a source page `sources/daily-note-YYYY-MM-DD.md` with a summary extracted by the distillation prompt
   - Enqueue for distillation to extract entities and concepts
4. For `MEMORY.md`:
   - Leave it as-is (it's the hot tier, not part of the wiki)
   - Optionally: enqueue a distillation pass to extract entities/concepts and cross-link them
5. Run the full distillation queue to populate entity and concept pages
6. Rebuild `index.md` from scratch
7. Append a migration entry to `log.md`
8. Commit everything as one git commit: `chore: bootstrap wiki from existing vault content`

### 10.2 Idempotency

Every write in the migration is idempotent via content hash. Running the migration twice is safe — existing pages are skipped, not duplicated.

### 10.3 Rollback

`git reset --hard HEAD~1` reverts the migration commit. Because the memory service index is derived from the vault, a rollback + `/admin/reindex` restores the previous state exactly.

### 10.4 Vault template update

`commandclaw-vault` repository gets a new commit that adds empty `wiki/index.md` and `wiki/log.md` to the template. New agents hatched from this template will have the wiki structure from day one, even before any ingestion happens.

---

## 11. Observability and ops

### 11.1 Langfuse tracing

Every memory service call is traced to Langfuse (existing instance). Trace attributes:

- `memory.endpoint`
- `memory.agent_id`
- `memory.namespace`
- `memory.page_type`
- `memory.search_mode`
- `memory.latency_ms`
- `memory.cache_hit` (true if served from LanceDB vs. rebuilt)
- `memory.fallback_activated` (true if degraded path)

### 11.2 Prometheus metrics

`/metrics` endpoint on the memory service exposes:

- `memory_requests_total{endpoint, status}`
- `memory_request_duration_seconds{endpoint}`
- `memory_search_latency_seconds{mode}`
- `memory_distill_queue_depth`
- `memory_distill_jobs_total{status}`
- `memory_lancedb_size_bytes`
- `memory_pages_total{type}`

### 11.3 Logging

Structured JSON logs to stdout. Correlated with Langfuse trace IDs via `X-Trace-Id` header.

### 11.4 docker-compose

A new service definition added to `commandclaw-mcp/docker-compose.yml` (which is the orchestration point for the mcp stack) or a separate `commandclaw-memory/docker-compose.yml`. To be decided in build phase.

```yaml
services:
  commandclaw-memory:
    build: ./commandclaw-memory
    ports:
      - "8284:8284"
    volumes:
      - ~/.commandclaw/workspaces:/workspaces:ro
      - ~/.commandclaw/memory:/data
    environment:
      - COMMANDCLAW_MEMORY_PORT=8284
      - COMMANDCLAW_MEMORY_CERBOS_URL=http://cerbos:3593
      - COMMANDCLAW_MEMORY_DISTILL_MODEL=gpt-4o-mini
    networks:
      - commandclaw-mcp_default
    depends_on:
      - cerbos
      - redis
```

---

## 12. Build phasing

Phases are ordered by dependency. Each phase is shippable on its own. No phase is considered done without tests.

### Phase 0 — Schema definition (prerequisite, no code)

- Finalize the vault layout in section 3 based on signoff feedback
- Lock the Pydantic model shapes for each page type
- Write `guiding_docs/MEMORY_SCHEMA.md` as the canonical reference

**Exit criteria**: schema doc reviewed and signed off.

### Phase 1 — Memory service skeleton

- New repo `commandclaw-memory`
- `pyproject.toml`, `Dockerfile`, `docker-compose.yml`
- FastAPI skeleton with `/health`, `/ready`, `/metrics`
- Config loader (Pydantic Settings)
- Pydantic models for all page types (from Phase 0)
- Unit tests for schema validation

**Exit criteria**: service starts, responds to `/health`, all schema tests pass.

### Phase 2 — Wiki CRUD + git writer

- `POST /wiki/pages`, `GET /wiki/pages/{type}/{slug}`, `PATCH`, `DELETE`
- `vault_writer` with synchronous git commit
- `index_writer` and `log_writer`
- Tests: write a page, verify git commit, verify index update, verify log append

**Exit criteria**: an end-to-end test can write a page via REST and see it in a freshly cloned vault.

### Phase 3 — Search (BM25 only, no embeddings)

- Tantivy index setup
- `GET /wiki/search?mode=bm25` returning results
- Incremental indexing on every wiki write
- Tests: write pages, search, verify rankings

**Exit criteria**: search returns relevant results at p95 latency under 30ms.

### Phase 4 — Search (vector + hybrid)

- LanceDB integration
- Embedding with `BGE-small-en-v1.5` (already cached in Docker image)
- `GET /wiki/search?mode=vector` and `?mode=hybrid` (RRF fusion)
- Tests: semantic similarity queries return relevant results
- Benchmark: p95 latency under 60ms at 10K pages

**Exit criteria**: hybrid search is live, latency target met.

### Phase 5 — Auth and RBAC

- Phantom token issuance via `POST /admin/enroll`
- HMAC signing/verification middleware
- Cerbos client + policy file
- Deny-by-default on Cerbos failure
- Tests: auth happy paths, failure paths, policy enforcement

**Exit criteria**: unauthenticated requests fail; unauthorized requests fail; valid requests succeed.

### Phase 6 — Distillation worker (rule-based first)

- JSONL queue
- Background asyncio worker
- Rule-based extractor (regex + heading patterns)
- `POST /distill/session`, `POST /ingest/source`, `GET /jobs/{job_id}`
- Tests: ingest a source, verify pages created, verify idempotency

**Exit criteria**: rule-based distillation produces valid wiki pages for a known test corpus.

### Phase 7 — Distillation worker (LLM-backed)

- LLM extractor with `gpt-4o-mini`
- Configurable via env var (`COMMANDCLAW_MEMORY_DISTILL_MODEL`)
- Prompt library in `distill/prompts.py`
- Tests: extraction accuracy against a fixture corpus
- Cost guardrails: per-job token budget, fallback to rule-based on budget exceeded

**Exit criteria**: LLM-backed distillation produces higher-quality pages than rule-based; cost per ingest is within budget.

### Phase 8 — Agent integration

- `MemoryServiceStore` shim in `commandclaw`
- New wiki tools (`wiki_search`, `wiki_read`, `wiki_ingest`, `wiki_lint`)
- `file_write` guard against paths under `wiki/`
- AGENTS.md template updates in `commandclaw-vault`
- Runtime wiring in `graph.py`
- Graceful degradation path
- Tests: end-to-end agent → memory service → vault roundtrip

**Exit criteria**: a spawned agent can ingest a source, query the wiki, and get cross-linked results.

### Phase 9 — Migration

- Bootstrap script
- Idempotency tests
- Rollback test
- Document the migration procedure in this PLAN.md

**Exit criteria**: migration runs cleanly on a seeded test vault; all existing content is represented in the wiki.

### Phase 10 — Observability and production readiness

- Langfuse tracing for all endpoints
- Prometheus metrics
- Structured logging
- docker-compose integration with existing mcp stack
- Load test: sustained 100 writes/sec, 1000 searches/sec
- Failure test: kill service mid-write, verify consistency

**Exit criteria**: the service can run unattended for 24 hours under synthetic load without data loss, index divergence, or memory leaks.

---

## 13. Open questions

Items that need a decision before or during implementation. Grouped by phase.

**Phase 0**

1. Are the four page types (source, entity, concept, synthesis) the right set, or do we need more (e.g., `decision`, `incident`, `session-summary`)?
2. Should `log.md` be a single file or rotated (`log/YYYY-MM.md`)? Karpathy's PRD uses single file; at long horizons this grows unbounded.
3. Do we need per-page content-hash deduplication, or is slug-based identity sufficient?

**Phase 2**

4. Git commit granularity: one commit per wiki write, or batched? Per-write is simpler but makes the log noisy. Batched improves readability but complicates rollback.
5. Should the memory service own its own clone of the vault, or share the agent's vault volume read-write? The agent containers are read-only except for `/workspace` — the memory service would need its own writable mount.

**Phase 4**

6. Which BGE variant for the distillation path — small-en-v1.5 (fast, less accurate) or M3 (slower, more accurate)? Beary recommends small-en for hot path, M3 for distill. Both are cached.

**Phase 5**

7. Does the memory service share the Cerbos instance with `commandclaw-mcp`, or run its own? Shared is simpler but couples failure domains.
8. How does agent enrollment interact with `spawn-agent.sh`? Today, a new agent is not auto-enrolled in `commandclaw-mcp`. Do we want to fix both at once, or keep it manual for now?

**Phase 7**

9. Does the distillation LLM run inside the memory service process, or as a separate worker container? Same-process is simpler; separate is more secure and limits blast radius.
10. Do we need a kill-switch for the distillation LLM (e.g., budget-based)? What's the budget?

**Phase 8**

11. How do agent sessions signal "end" to trigger distillation? Today, there's no explicit session-end. Does the agent need a new state node, or can we use Telegram `/done` + timeout?

**Phase 10**

12. Do we put the memory service in the same docker-compose as `commandclaw-mcp`, or a separate one? Same is more cohesive; separate gives clearer boundaries.

---

## 14. What this plan does not cover

Tracked separately so this plan doesn't grow indefinitely.

- **Telegram on LangGraph runtime port** — existing gap, tracked in the last devlog
- **Scheduler/cron** — Week Two vision item, needs its own plan
- **Multi-agent coordination beyond memory sharing** — out of scope
- **Automatic `commandclaw-mcp` agent enrollment in `spawn-agent.sh`** — tracked in devlog followups
- **A fresh round of PLAN.md for Telegram + scheduler** — will come after this one ships

---

## Signoff

This plan is not to be implemented until the following is decided:

- [ ] Page types in section 3 are finalized
- [ ] Build phase order in section 12 is approved
- [ ] Open questions 1–5 (phases 0–2) have answers
- [ ] The separate `commandclaw-memory` repo structure is approved
- [ ] Shikhar has reviewed and signed off on this document

Open questions for later phases (6–12) can be answered as those phases begin.
