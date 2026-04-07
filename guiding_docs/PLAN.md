# PLAN.md — Memory Layer Implementation

**Status:** DRAFT — awaiting signoff before implementation begins.
**Date:** 2026-04-07 (revision 2 — wiki split into its own repo)
**Supersedes:** [archive/PLAN-2026-04-06.md](archive/PLAN-2026-04-06.md)

This plan defines exactly what to build to give CommandClaw a proper memory layer, based on the synthesis of two independent design inputs:

- **[MEMORY_PRD_KARPATHY.md](MEMORY_PRD_KARPATHY.md)** — Andrej Karpathy's LLM Wiki pattern. Defines the *data model* and *workflow contract*: markdown wiki the LLM maintains, `index.md` as a content catalog, `log.md` as a chronological audit, ingest/query/lint operations.
- **[whitepaper-output/commandclaw-memory-service/](../whitepaper-output/commandclaw-memory-service/whitepaper/commandclaw-memory-service-whitepaper.md)** — BEARY whitepaper. Defines the *infrastructure*: FastAPI microservice, LanceDB + BM25 hybrid retrieval, Cerbos RBAC, HMAC auth, distillation worker, git-first sync.

These are not alternatives. They are complementary layers:

| Layer | Source | Job |
|---|---|---|
| **Data model + workflow** | Karpathy PRD | What lives in the wiki, how it's structured, the contract between human and agent |
| **Infrastructure + enforcement** | BEARY whitepaper | How the wiki is stored, indexed, retrieved, validated, secured, and distilled |

The design principle underneath both: **CommandClaw is built for enterprise reliability, which means it must work with cheap or weak models, not only with frontier Claude models.** A cheap model cannot be trusted to self-maintain a wiki the way Karpathy's workflow assumes. The memory service is the discipline layer that enforces the schema the LLM is supposed to follow — so that when the LLM gets it wrong, the service rejects the write instead of corrupting the knowledge base.

## What changed in this revision

The previous draft placed the wiki inside each agent's vault as a `wiki/` subtree. That collapsed two concerns that should stay separate:

- **Vault** (`commandclaw-vault`) — per-agent, private, the control plane: IDENTITY, AGENTS.md, USER.md, MEMORY.md, daily notes, installed skills. One vault per agent. Read-editable by the agent's human operator.
- **Wiki** (`commandclaw-wiki`, NEW) — cross-agent, durable knowledge base: sources, entities, concepts, syntheses. One shared wiki per deployment. Written only through the memory service.

Putting the wiki in the vault would mean every agent has its own copy of shared knowledge (duplication), the memory service would have to reach into per-agent vault mounts to write (leaky boundary), and agents could trample wiki structure via `file_write` on accident (broken guarantee). Splitting them is the correct move.

The consequence: **three repositories are in scope for this plan**, not two.

| Repository | Status | Role |
|---|---|---|
| `commandclaw-wiki` | **NEW** | The wiki repo — markdown schema, templates, seed index/log, AGENTS.md schema doc |
| `commandclaw-memory` | **NEW** | FastAPI microservice that owns the wiki repo's working copy, validates writes, indexes, distills, serves queries |
| `commandclaw-vault` | existing | Per-agent control plane. Gains no `wiki/` subtree. Unchanged except for an AGENTS.md update teaching agents how to use the memory service. |

---

## Table of Contents

1. [Scope and non-scope](#1-scope-and-non-scope)
2. [Architecture overview](#2-architecture-overview)
3. [The wiki repository — `commandclaw-wiki`](#3-the-wiki-repository--commandclaw-wiki)
4. [The memory service — `commandclaw-memory`](#4-the-memory-service--commandclaw-memory)
5. [Schema enforcement](#5-schema-enforcement)
6. [Distillation pipeline](#6-distillation-pipeline)
7. [Agent integration](#7-agent-integration)
8. [Auth, tenancy, and RBAC](#8-auth-tenancy-and-rbac)
9. [Failure modes and graceful degradation](#9-failure-modes-and-graceful-degradation)
10. [Bootstrap and migration](#10-bootstrap-and-migration)
11. [Observability and ops](#11-observability-and-ops)
12. [Wiki reading and browsing](#12-wiki-reading-and-browsing)
13. [Build phasing](#13-build-phasing)
14. [Open questions](#14-open-questions)
15. [What this plan does not cover](#15-what-this-plan-does-not-cover)

---

## 1. Scope and non-scope

### In scope

- New repository `commandclaw-wiki` — the git repo that holds the actual wiki content. Ships with a seed `index.md`, seed `log.md`, empty `sources/entities/concepts/syntheses/` directories, an `AGENTS.md` schema-reference doc, and a `README.md`. This repo is never edited by hand in production; the memory service is the sole writer.
- New repository `commandclaw-memory` — FastAPI microservice. Owns a working clone of `commandclaw-wiki`, validates writes against the schema, commits to the clone, pushes upstream on some cadence, runs the LanceDB + BM25 indexes, runs the distillation worker, integrates with Cerbos.
- New `MemoryServiceStore` class in `commandclaw` implementing LangGraph `BaseStore` interface
- Schema enforcement on wiki writes (Pydantic models, frontmatter validation)
- Distillation worker (configurable model, background asyncio task)
- Auth consistent with `commandclaw-mcp` (phantom token + HMAC + Cerbos)
- Four new native wiki tools in `commandclaw` (`wiki_search`, `wiki_read`, `wiki_ingest`, `wiki_lint`)
- Bootstrap script that initializes `commandclaw-wiki` from an empty seed and optionally ingests content from existing agent vaults
- AGENTS.md section in the vault template documenting how agents should use the memory service
- Docker compose integration alongside existing `commandclaw-mcp`

### Out of scope for this plan

- Multi-machine deployment (single-machine is the target)
- Kubernetes, cloud orchestration
- Replacing the existing `commandclaw-mcp` gateway
- Changing the LangGraph runtime, NeMo Guardrails, or Langfuse integration
- Embedding model changes (`BGE-small-en-v1.5` for hot-path retrieval, pre-cached)
- Per-tenant wiki repos (one shared wiki per deployment for v1; multi-tenant is an upgrade path called out in open questions)
- Scheduler/cron (separate concern — belongs in a future plan)
- Telegram runtime port to LangGraph (tracked separately as a gap)
- Any work on `commandclaw-skills` or `commandclaw-observe`

### Explicitly preserved

- The `commandclaw-vault` structure does **not** change. Vault stays as the per-agent control plane. No `wiki/` subtree is added. Agents continue to write `MEMORY.md`, `memory/YYYY-MM-DD.md`, and identity files to their vault via existing file tools.
- `MEMORY.md` stays as the hot-tier file loaded into the system prompt on every invocation. Its role does not change. It is *not* part of the wiki.
- The `memory/YYYY-MM-DD.md` daily notes stay in the vault. They are private to the agent by default. If content from a daily note should live in the shared wiki, the agent (or user) explicitly calls `wiki_ingest` on it — there is no automatic vault→wiki flow.
- The git vault and the git wiki repo are both authoritative for their own scope. LanceDB is a derived index over the wiki repo only.

---

## 2. Architecture overview

```
┌────────────────────────────────────────────────────────────────────┐
│  Per-agent container (one per agent)                               │
│                                                                    │
│  LangGraph runtime                                                 │
│    ├─ Native tools (bash, file_*, memory_*, skill_*)               │
│    ├─ Wiki tools (wiki_search, wiki_read, wiki_ingest, wiki_lint)  │
│    ├─ MemoryServiceStore (BaseStore shim) ────────────┐            │
│    └─ MCP tools (via commandclaw-mcp) ─────────────┐  │            │
│                                                    │  │            │
│  Vault mount: /workspace (writable)                │  │            │
│    (private to this agent — NOT mounted into       │  │            │
│     the memory service)                            │  │            │
└────────────────────────────────────────────────────┼──┼────────────┘
                                                     │  │
                            HTTP (loopback)          │  │
                      port 8283  ◄───────────────────┘  │
                      port 8284  ◄──────────────────────┘
                                                     │  │
                      ┌──────────────┐    ┌──────────▼──▼──────┐
                      │ commandclaw- │    │ commandclaw-memory │
                      │     mcp      │    │     (new)          │
                      │  (existing)  │    │                    │
                      │              │    │  FastAPI :8284     │
                      │  Tools RBAC  │    │  LanceDB (warm)    │
                      │  Credential  │    │  Tantivy (BM25)    │
                      │  injection   │    │  Schema validator  │
                      └──────┬───────┘    │  Distill worker    │
                             │            │  Cerbos client     │
                             │            │                    │
                             │            │  Wiki mount:       │
                             │            │  /wiki (writable)  │
                             │            └──────┬─────────────┘
                             │                   │
                             │                   │ git commit (sync)
                             │                   │ git push  (async)
                             │                   ▼
                             │       ┌────────────────────────────┐
                             │       │  commandclaw-wiki (git)    │
                             │       │  (NEW — one per deploy)    │
                             │       │                            │
                             │       │  README.md                 │
                             │       │  AGENTS.md (schema doc)    │
                             │       │  index.md    (service-     │
                             │       │  log.md       maintained)  │
                             │       │  sources/                  │
                             │       │  entities/                 │
                             │       │  concepts/                 │
                             │       │  syntheses/                │
                             │       └────────────────────────────┘
                             │
                             │  (MCP gateway does not touch the vault
                             │   or the wiki — it only proxies tools)
                             ▼
                      ┌──────────────────────────────────────┐
                      │  External MCP servers (as today)     │
                      └──────────────────────────────────────┘


   Per-agent vault (one per agent, unchanged)
   ┌──────────────────────────────────────┐
   │  commandclaw-vault clone             │
   │  at ~/.commandclaw/workspaces/<id>/  │
   │                                      │
   │  MEMORY.md          ← hot tier       │
   │  memory/*.md        ← daily notes    │
   │  IDENTITY.md                         │
   │  AGENTS.md                           │
   │  USER.md                             │
   │  .agents/skills/                     │
   │                                      │
   │  Mounted ONLY into the agent's       │
   │  container. The memory service does  │
   │  NOT see this volume.                │
   └──────────────────────────────────────┘
```

Key invariants:

1. **Two git repos, two scopes.** `commandclaw-vault` is per-agent private state. `commandclaw-wiki` is cross-agent shared knowledge. The memory service never reads or writes a vault; the agent never directly reads or writes the wiki repo.
2. **The wiki repo is the source of truth for all indexed memory.** LanceDB and BM25 are always rebuildable from it.
3. **Writes are synchronous to git, async to the index.** The memory service's local wiki clone is committed to *before* the HTTP response returns. Remote push is a separate async operation. Index (LanceDB/BM25) updates are eventual.
4. **The memory service is the sole writer to the wiki repo.** No agent process touches the wiki repo at the filesystem level. No agent process touches LanceDB directly.
5. **Agent code uses the `BaseStore` shim and the four wiki tools.** It doesn't import LanceDB, doesn't know the memory service port, doesn't construct HTTP clients directly, doesn't have a filesystem path to the wiki.
6. **Physical isolation makes schema enforcement trivial.** Because the wiki repo is not mounted into agent containers, `file_write` cannot corrupt it even if the agent tries. The only path into the wiki is through the validated REST boundary.
7. **Hot path never waits on distillation.** Distillation is a background worker. Agent writes and reads do not block on it.
8. **All vault→wiki flow is explicit.** If content from an agent's daily notes should enter the wiki, the agent (or user) calls `wiki_ingest` passing the content inline. There is no automatic filesystem watching, no vault-level git hook, no implicit promotion.

---

## 3. The wiki repository — `commandclaw-wiki`

`commandclaw-wiki` is a new git repository, independent of `commandclaw-vault`. It is cloned once per deployment into the memory service's working directory (`/wiki` inside the memory container; `~/.commandclaw/wiki/` on the host) and is modified only by the memory service. The wiki follows Karpathy's LLM Wiki pattern, refined for enterprise discipline through schema enforcement.

### 3.1 Repository layout

```
commandclaw-wiki/
├── README.md                 # Describes what the repo is, who writes it, the warning
│                             # that it is service-managed and not for hand edits
├── AGENTS.md                 # Schema reference. The canonical spec for all page
│                             # types, frontmatter fields, conventions, and the
│                             # ingest/query/lint workflow. Read by the distillation
│                             # LLM and by any human operator inspecting the repo.
├── LICENSE
├── .gitignore                # Excludes any lockfiles, editor scratch, etc.
├── index.md                  # Content catalog (service-maintained — do not hand-edit)
├── log.md                    # Append-only audit log (service-maintained)
├── sources/                  # One page per ingested raw source
│   └── <slug>.md
├── entities/                 # Per-entity pages (people, projects, tools, places)
│   └── <slug>.md
├── concepts/                 # Per-concept pages (abstract topics, principles)
│   └── <slug>.md
├── syntheses/                # Cross-cutting synthesis pages (LLM-generated analyses)
│   └── <slug>.md
└── _seed/                    # Shipping content: a `README-page.md`, an initial
                              # entity page for "commandclaw" itself, concept pages
                              # seeded from existing whitepapers. Gives a fresh
                              # deployment a non-empty starting state.
```

**Why a seed/ directory instead of starting empty.** A completely empty wiki on first boot gives agents nothing to search, which makes `wiki_search` look broken in smoke tests. The seed contains a small set of valid pages that exercise every page type, pass all schema validation, and give a realistic first-query experience. They can be deleted later if they're not wanted.

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

A new git repository and Python package: `commandclaw-memory`. This is the FastAPI service that owns the `commandclaw-wiki` working clone.

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
│   │       ├── admin.py         # Reindex, stats, bootstrap
│   │       └── health.py        # Liveness/readiness
│   ├── wiki_repo/
│   │   ├── clone_manager.py     # Clone/pull of commandclaw-wiki on startup,
│   │   │                        #   `git push` scheduler, conflict recovery
│   │   ├── wiki_writer.py       # Schema-validated write to the wiki clone
│   │   │                        #   (writes file, updates index.md, appends
│   │   │                        #   log.md, single git commit)
│   │   ├── index_writer.py      # Rewrites /wiki/index.md
│   │   └── log_writer.py        # Appends to /wiki/log.md
│   ├── storage/
│   │   ├── lancedb_store.py     # LanceDB writer/reader
│   │   └── bm25_store.py        # Tantivy BM25 index
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
│   └── bootstrap/
│       └── seed_from_vaults.py  # One-shot ingest from existing vault content
└── tests/
    ├── test_schema.py
    ├── test_wiki_crud.py
    ├── test_clone_manager.py
    ├── test_search.py
    ├── test_distill.py
    └── test_bootstrap.py
```

### 4.1a Wiki clone lifecycle

The memory service holds a single writable clone of `commandclaw-wiki`:

- **At startup**: if `$COMMANDCLAW_MEMORY_WIKI_PATH` exists and is a git repo, the service runs `git fetch && git reset --hard origin/main` (or configured branch). If it does not exist, the service runs `git clone $COMMANDCLAW_MEMORY_WIKI_REMOTE $COMMANDCLAW_MEMORY_WIKI_PATH`.
- **On every successful write**: the service commits to the local clone. The commit is synchronous — the HTTP response does not return until the commit has completed.
- **Push cadence**: pushes to the remote are **async and batched**. A background task pushes the local branch every `COMMANDCLAW_MEMORY_PUSH_INTERVAL` seconds (default 60) when there are unpushed commits. This keeps the hot path fast without sacrificing durability — if the service crashes, the unpushed commits are still present in the local clone and will push on next startup.
- **Conflict handling**: if `git push` is rejected because the remote has advanced (another deployment, human edit, or a rebase), the service pulls with `--rebase=false` (merge commit) and retries the push. If the merge itself conflicts, the service refuses further writes and surfaces a `503` with a `wiki_push_blocked` reason. Recovery is a manual operator action.
- **Single-writer invariant**: only one memory service instance may hold the writable clone for a given wiki. Running two instances against the same wiki repo is unsupported and will cause divergence. For v1 there is no leader election; we rely on deployment convention.

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
| `POST` | `/admin/reindex` | Full rebuild of LanceDB and BM25 from the wiki repo clone. Admin only. |
| `POST` | `/admin/wiki/pull` | Force a `git fetch && git reset --hard origin/main` on the wiki clone, then re-index. Admin only. |
| `POST` | `/admin/wiki/push` | Force an immediate push of any unpushed commits. Admin only. |
| `POST` | `/admin/bootstrap` | Run the one-shot seed-from-vaults bootstrap (section 10). Admin only. |
| `GET` | `/admin/stats` | Page counts by type, search latency percentiles, queue depths, unpushed commit count. |
| `POST` | `/admin/enroll` | Register a new agent principal (agent_id + token + hmac_key). |

**Operational**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness. Cheap. |
| `GET` | `/ready` | Readiness. Checks LanceDB, Tantivy, wiki clone is a valid git repo, Cerbos reachable. |
| `GET` | `/metrics` | Prometheus-compatible metrics. |

### 4.3 Data flow on a wiki page write

1. Agent calls `POST /wiki/pages` via the `MemoryServiceStore` shim
2. Auth middleware verifies phantom token + HMAC signature
3. Cerbos middleware checks `principal={agent_id, role}` can write this page type in this namespace
4. Schema validator parses the body as the appropriate Pydantic model for the page type
5. Cross-reference validator checks that all `sources`, `entities`, `concepts` listed in frontmatter actually exist in the wiki clone (or are being created atomically in the same request)
6. `wiki_writer` writes the markdown file to the wiki clone on disk and commits synchronously
7. `index_writer` rewrites `index.md` in the same commit
8. `log_writer` appends to `log.md` in the same commit
9. `lancedb_store.enqueue(page)` — async, returns immediately
10. `bm25_store.enqueue(page)` — async, returns immediately
11. Response returned to agent: `{page_id, path, git_commit_sha}`
12. (later, async) Background push task pushes new commits to the wiki remote on the configured interval

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

The memory service is the only writer to the wiki repo. Agents cannot reach the wiki filesystem — the wiki clone is mounted into the memory service container, not into any agent container. There is nothing to guard with a `file_write` check because the path simply does not exist from the agent's perspective.

This physical isolation is the enforcement mechanism. Every write to the wiki must come through a REST endpoint, and every REST write is validated by the service before it touches git.

The memory service validates every write via Pydantic models (`schema/models.py`), one per page type. A write fails if:

- Frontmatter is malformed
- Required fields are missing
- `type` doesn't match the path (`sources/` must have `type: source`)
- `slug` doesn't match the filename
- Referenced sources/entities/concepts don't exist
- Content is empty or shorter than a minimum length
- The page would create a circular `supersedes` chain

Why this matters for enterprise: a cheap model will occasionally generate malformed frontmatter, skip required fields, or invent slugs for entities that don't exist. Without enforcement, the wiki rots silently. With enforcement, the service returns `422 Unprocessable Entity` and the agent has to fix its output — the wiki stays consistent regardless of which model is driving.

The vault remains untouched by schema enforcement. Agents can write whatever they want to `MEMORY.md` or `memory/*.md` in their own vault using `file_write` — that content is private to the agent and never flows into the wiki automatically. The wiki/vault split gives us clean semantics: the vault is the agent's scratchpad, the wiki is the disciplined shared knowledge base.

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

Distillation is always explicitly triggered via REST. There is no filesystem watching and no vault-level git hook. This keeps the wiki/vault boundary clean — the memory service does not know that vaults exist.

- **Session end**: the agent calls `POST /distill/session` with the session transcript as the request body
- **Explicit ingest**: the agent calls `POST /ingest/source` passing a URL, raw text, or an opaque content blob the user handed it
- **Daily-note promotion**: if the user wants a daily note distilled into the wiki, the agent reads the note from the vault with `file_read` and passes the contents to `POST /ingest/source`. The memory service never reaches into a vault on its own.
- **Lint pass**: `POST /lint` may discover a missing page and enqueue a distillation to create it

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

Two documents need updating, one in each repo.

**`commandclaw-vault/AGENTS.md` (template update)** — teaches the agent how to use the memory service from inside a session:

- What the wiki is and how it differs from the vault: the vault is this agent's private scratchpad, the wiki is the shared knowledge base that persists across agents and sessions
- How to query via `wiki_search` and `wiki_read`
- How to ingest a new source via `wiki_ingest` (URL, text, or a vault file read via `file_read` first)
- When to run `wiki_lint` (periodically, and after a batch ingest)
- How distillation works so the agent doesn't duplicate what the worker does automatically at session end
- That the agent can never directly write to the wiki — the service is the only writer

**`commandclaw-wiki/AGENTS.md` (schema reference, NEW)** — the canonical schema doc for the wiki itself:

- All page types and their required/optional frontmatter fields
- Slug conventions (lowercase, dash-separated, globally unique within a type)
- Cross-reference rules (a source must exist before an entity can reference it)
- The `supersedes` / `superseded_by` contract for page updates
- Ingest/query/lint workflow prose, adapted from the Karpathy PRD
- Examples of well-formed pages for each type

This doc is read by the distillation LLM as part of its prompt, giving a weak model an in-context specification to follow. It is also the canonical reference for any human operator inspecting the wiki.

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

One wiki repo, many agents. Every page has an `agent_id` field in frontmatter recording who created it. Namespace prefixes live in the directory structure of the wiki repo:

```
commandclaw-wiki/
  sources/                   # Shared across all agents by default
  entities/
  concepts/
  syntheses/
  private/<agent_id>/        # Optional per-agent private space inside the shared wiki
    sources/
    entities/
    concepts/
    syntheses/
```

- **Default**: all writes land in the top-level type directories (`sources/`, `entities/`, etc.) and are readable by every agent in the deployment. This is the expected 99% case — the whole point of a shared wiki is that agents build shared knowledge.
- **Private spill**: if an agent has knowledge that should persist in the wiki but not be visible to other agents, it can write to `private/<agent_id>/…`. Reads from `private/<agent_id>/` are restricted by Cerbos to that agent (or admin). This is a deliberate feature, not the default, and requires the agent to pass `namespace=private` explicitly.
- **Note**: this "private" is not the same as the vault. The vault is *actually* private per agent because it's physically mounted only into that agent's container. `private/<agent_id>/` in the wiki is RBAC-enforced, not physically isolated — a bug in Cerbos policies could leak it. Use the vault for truly secret content and the wiki for knowledge-you-want-to-durably-index.

**For v1, private namespaces are optional.** The MVP is "one shared wiki where every agent writes to the top-level type directories." Private namespaces can be added in a later phase if a concrete need emerges.

### 8.3 RBAC via Cerbos

Existing Cerbos instance is reused (see open question 7 for "shared instance vs. dedicated"). A new policy file `commandclaw-memory/policies/memory_service.yaml` is added, covering the memory service's resource kinds (`wiki_page`, `wiki_search`, `admin`). Example rules for v1:

- Any enrolled agent can write to and read from the top-level type directories (`sources/`, `entities/`, `concepts/`, `syntheses/`)
- Any enrolled agent can write to and read from its own `private/<agent_id>/` subtree
- No enrolled agent can read another agent's `private/<agent_id>/` subtree
- Only `admin` role can use `DELETE` endpoints, `/admin/*` endpoints, or write to `private/<other_agent>/`
- Reads from `/wiki/search` are filtered by Cerbos after retrieval — results from a private subtree are excluded if the caller lacks permission

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

## 10. Bootstrap and migration

There are two distinct "day zero" operations: provisioning the wiki repo itself, and optionally seeding it from existing vault content. These used to be the same step when the wiki lived inside the vault; now they're separate.

### 10.1 Provisioning the wiki repo

`commandclaw-wiki` is created once, manually, by the operator. It is a normal git repo hosted on the operator's preferred forge (GitHub, a self-hosted Gitea, etc.). It ships as a **template repo** with:

- Empty (but valid) `index.md` and `log.md`
- Empty `sources/`, `entities/`, `concepts/`, `syntheses/` directories, each with a `.gitkeep`
- The `AGENTS.md` schema reference (section 7.3)
- A `README.md` warning "this repo is service-managed, do not hand-edit"
- The `_seed/` directory with a small set of valid starter pages

The operator clones the template to create a new deployment wiki, sets `COMMANDCLAW_MEMORY_WIKI_REMOTE=<clone-url>` in the memory service env, and starts the service. The service clones the repo on first boot.

### 10.2 Seeding from existing agent vaults (optional, one-shot)

An existing CommandClaw deployment has per-agent vaults with `MEMORY.md` and `memory/*.md`. The operator may want to bootstrap the wiki by distilling that existing content.

Triggered by: `POST /admin/bootstrap` with a JSON body listing vault paths to ingest. Or equivalently: `python -m commandclaw_memory.bootstrap seed-from-vaults --vaults /path/1 /path/2`.

Steps performed by the service:

1. For each vault path listed:
   - For each file under `memory/*.md`: read contents, submit to `POST /ingest/source` with `source_type=daily-note`, `source_agent_id=<vault-owner>`, and the file content as the body. Each submission enters the distill queue.
   - Read `MEMORY.md` (optional, per flag): submit as a single ingest with `source_type=memory-hot-tier`.
2. Wait for the distill queue to drain.
3. Run a `POST /lint` pass to catch any dangling references.
4. Append a `bootstrap` entry to `log.md` listing the vault paths ingested and the page counts produced.
5. Push the accumulated commits to the wiki remote.

This bootstrap is **not** necessary for a fresh deployment. A new wiki can start empty and grow only from explicit `wiki_ingest` calls during normal operation.

### 10.3 Idempotency

Every ingest write is idempotent via content hash. Running the bootstrap twice on the same vaults is safe — existing pages with matching content are skipped, not duplicated. Pages whose content has changed since the last ingest are updated with a new `supersedes` link to the prior version.

### 10.4 Rollback

Because the wiki is a normal git repo, rollback is a normal git operation:

```
git reset --hard <pre-bootstrap-commit>
git push --force-with-lease
```

After a forced rollback, the operator calls `POST /admin/reindex` on the memory service to rebuild LanceDB and BM25 from the reset state. The memory service does not do this automatically because forced rollbacks are operator actions that should be explicit.

### 10.5 No vault template changes

Unlike revision 1 of this plan, **the `commandclaw-vault` template is not modified** to include a `wiki/` subtree. Fresh agents get no new files in their vault. The only vault change is the `AGENTS.md` update described in section 7.3 that teaches the agent how to use the memory service — and even that is additive, not structural.

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

A new service definition added to `commandclaw-mcp/docker-compose.yml` (the orchestration point for the cross-repo stack) or a separate `commandclaw-memory/docker-compose.yml`. To be decided in build phase — see open question 12.

```yaml
services:
  commandclaw-memory:
    build: ./commandclaw-memory
    ports:
      - "8284:8284"
    volumes:
      # The wiki repo clone — writable, service-owned.
      # Persisted on the host so it survives container restarts.
      - ~/.commandclaw/wiki:/wiki
      # LanceDB + BM25 derived indexes and distill queue
      - ~/.commandclaw/memory/data:/data
    environment:
      - COMMANDCLAW_MEMORY_PORT=8284
      - COMMANDCLAW_MEMORY_WIKI_PATH=/wiki
      - COMMANDCLAW_MEMORY_WIKI_REMOTE=git@github.com:FnSK4R17s/commandclaw-wiki.git
      - COMMANDCLAW_MEMORY_WIKI_BRANCH=main
      - COMMANDCLAW_MEMORY_PUSH_INTERVAL=60
      - COMMANDCLAW_MEMORY_CERBOS_URL=http://cerbos:3593
      - COMMANDCLAW_MEMORY_DISTILL_MODEL=gpt-4o-mini
    networks:
      - commandclaw-mcp_default
    depends_on:
      - cerbos
      - redis
```

**Note the vault is not mounted.** The memory service never touches per-agent vaults. The only git repo it sees is the wiki repo at `/wiki`.

---

## 12. Wiki reading and browsing

The wiki repo holds the data; it does not render itself. We need at least one human-facing reader so an operator can inspect what the agents have built up. None of these readers writes to the wiki — they are strictly read-only consumers of the git repo and never talk to the memory service.

There are three audiences with different needs:

| Audience | Who | What they need | Recommended viewer |
|---|---|---|---|
| **Operator / debug** | Shikhar, anyone running the deployment | Fast inspection of what the service just wrote, graph view, backlinks, search, no setup | **Obsidian**, opened against the wiki clone on disk |
| **Stakeholder / read-only** | Anyone who should *see* the wiki without being able to edit it | Browsable URL, looks like a knowledge base, search, full-text discovery | **Quartz** static site, deployed via GitHub Action on every push to `main` |
| **Anyone with a CLI** | Power users, scripts, headless environments | Search and read pages from the terminal | The memory service's REST API directly, or a small `cclaw wiki` CLI wrapper |

### 12.1 Operator view: Obsidian against the wiki clone

The wiki clone on the host (`~/.commandclaw/wiki/`) is a directory of markdown with YAML frontmatter. That is exactly what Obsidian wants. To use it:

1. Open Obsidian
2. "Open folder as vault" → `~/.commandclaw/wiki/`
3. Done

Out of the box you get: full-text search, graph view, backlinks, frontmatter rendering, and clickable wikilinks (since our pages cross-reference each other in the body). For free, with no service to run.

A small `commandclaw-wiki/.obsidian/` directory is committed to the repo with a sensible default config:

- Light/dark theme switching
- Frontmatter visible by default in source mode
- Graph view colored by page type (`source`, `entity`, `concept`, `synthesis`)
- Search restricted to body text by default (frontmatter often has long URLs that pollute results)
- A note saying "this Obsidian config is for read-only inspection — do not edit pages from Obsidian, use the memory service REST API"

The Obsidian Git plugin is **disabled** in the committed config — operators should not be auto-pushing accidental edits from a Reader-style workflow. The wiki is service-managed.

**Operators on macOS/Linux who don't want Obsidian** can use [Logseq](https://logseq.com/) or [Foam](https://foambubble.github.io/foam/) (VS Code extension) — both consume the same on-disk format.

### 12.2 Published view: Quartz static site

[Quartz](https://quartz.jzhao.xyz/) is a static-site generator built specifically for publishing markdown vaults with frontmatter, wikilinks, backlinks, graph view, and full-text search. It is the closest match to "render `commandclaw-wiki` as a Wikipedia-shaped browsable site."

The deployment pattern:

1. A `quartz/` subdirectory inside `commandclaw-wiki` holds the Quartz config (theme, navigation, layout).
2. A GitHub Actions workflow (`.github/workflows/publish.yml`) on the wiki repo runs on every push to `main`:
   - Checks out the repo
   - Installs Quartz
   - Builds the static site from the wiki content
   - Publishes to GitHub Pages (or any static host) at e.g. `https://wiki.commandclaw.dev/`
3. The published site is read-only by construction — there is no write path back to the repo. To change a page, the memory service must commit to the repo, the Action re-runs, the site updates.

Why Quartz over alternatives:

- **MkDocs Material** is lovely but expects a `nav:` configuration in `mkdocs.yml`. Our wiki is dynamic — pages come and go via the service. A docs-shaped tool with hand-curated navigation is the wrong fit. Quartz auto-discovers everything in the directory.
- **Docusaurus** is React-heavy and oriented toward versioned product docs. Overkill.
- **BookStack / Wiki.js / Outline** are full applications with their own databases. They want to *be* the wiki, not render an existing one. Wrong layer.
- **Astro Starlight** is closer to MkDocs in spirit — also docs-shaped.

Quartz handles our specific shape (frontmatter-heavy, wikilinks, no curated nav) natively.

**Theme**: Quartz ships with a default that looks like a personal knowledge graph (sidebar with backlinks, graph view in the corner). For an enterprise feel we can swap to a more "docs-like" layout via Quartz's theme system without changing any wiki content.

**Auth on the published site**: out of scope for v1. The published site is either fully public or behind a static-host access control (Cloudflare Access, GitHub Pages with org restrictions, etc.). If we need fine-grained per-page auth, we'd switch from Quartz to a server-side renderer — a separate decision deferred until there's a concrete need.

### 12.3 CLI view: REST API directly or `cclaw wiki` wrapper

For headless environments or scripted workflows:

```bash
# Read a page
curl -H "Authorization: Bearer $TOKEN" \
  https://memory.local:8284/wiki/pages/concepts/llm-wiki

# Search
curl -H "Authorization: Bearer $TOKEN" \
  "https://memory.local:8284/wiki/search?query=memory+architecture&mode=hybrid"

# Get the index as JSON
curl -H "Authorization: Bearer $TOKEN" \
  https://memory.local:8284/wiki/index
```

A small `cclaw wiki` CLI wrapper (in the `commandclaw` repo, alongside the existing entry point) can sugar these — `cclaw wiki search "memory"`, `cclaw wiki read concepts/llm-wiki`, `cclaw wiki index`. This is a Phase 9 deliverable, not a separate project.

### 12.4 What we are not building

- **No custom web viewer.** Quartz is enough. Building a bespoke React app to view the wiki is a poor use of time when an off-the-shelf static site generator handles 95% of the need.
- **No live rendering inside the memory service.** The memory service is an API, not a web app. The viewer story is "static site built from git."
- **No editor UI.** The wiki is service-written and Obsidian/Quartz are read-only. If a human wants to write content into the wiki, they go through the memory service's REST API just like an agent does — typically by calling `wiki_ingest` with the source content.
- **No real-time push.** Quartz rebuilds on every git push (which happens on the configured cadence in the memory service). There is a small window — up to `PUSH_INTERVAL` seconds — between a write landing in the local clone and being visible on the published site. This is acceptable.
- **No graph database.** Cross-references in frontmatter give us the graph for free; LanceDB gives us semantic similarity. We don't need Neo4j or a property graph store.

### 12.5 Phase placement

The reader stack is split across two phases:

- **Phase 1 (the `commandclaw-wiki` repo)**: ship the `.obsidian/` config and the `quartz/` directory + GitHub Action as part of the template. From the moment the repo exists, both reading paths work. No code in `commandclaw-memory` is involved.
- **Phase 9 (agent integration)**: ship the optional `cclaw wiki` CLI wrapper as a small addition to the existing `commandclaw` entry point.

The reader stack adds **zero** ops surface to the memory service itself — it is entirely on the consumer side of the wiki repo.

---

## 13. Build phasing

Phases are ordered by dependency. Each phase is shippable on its own. No phase is considered done without tests.

### Phase 0 — Schema definition (prerequisite, no code)

- Finalize the wiki schema in section 3 based on signoff feedback
- Lock the Pydantic model shapes for each page type
- Write `guiding_docs/MEMORY_SCHEMA.md` as the canonical reference (also published as `AGENTS.md` in the wiki repo during Phase 1)

**Exit criteria**: schema doc reviewed and signed off.

### Phase 1 — `commandclaw-wiki` repo (no service code, just the repo + viewers)

- New repo `commandclaw-wiki` as a template repo
- Seed `README.md`, `AGENTS.md` (schema reference from Phase 0), `LICENSE`, `.gitignore`
- Empty `sources/entities/concepts/syntheses/` with `.gitkeep`
- Empty but valid `index.md` and `log.md`
- Small `_seed/` directory with a handful of valid starter pages that exercise every page type
- `.obsidian/` directory with the operator-view config from section 12.1
- `quartz/` directory with Quartz config + theme (per section 12.2)
- `.github/workflows/publish.yml` GitHub Action that builds Quartz on every push to `main` and deploys to GitHub Pages
- Clone it to create the first deployment wiki repo (e.g. `FnSK4R17s/commandclaw-wiki-main`)

**Exit criteria**: repo exists, passes a first-pass schema-lint script (to be shipped in Phase 3), can be cloned by an automated script, opens cleanly in Obsidian, and the Quartz Action publishes the seed content to a public URL.

### Phase 2 — Memory service skeleton

- New repo `commandclaw-memory`
- `pyproject.toml`, `Dockerfile`, `docker-compose.yml`
- FastAPI skeleton with `/health`, `/ready`, `/metrics`
- Config loader (Pydantic Settings) with wiki repo settings (`WIKI_PATH`, `WIKI_REMOTE`, `WIKI_BRANCH`, `PUSH_INTERVAL`)
- Clone manager (`wiki_repo/clone_manager.py`) — clones or fetches the wiki repo on startup
- Pydantic models for all page types (from Phase 0)
- Unit tests for schema validation
- Integration test: service boots, clones the wiki repo, exposes `/ready` green

**Exit criteria**: service starts against a clean wiki repo clone, responds to `/ready`, all schema tests pass.

### Phase 3 — Wiki CRUD + git writer

- `POST /wiki/pages`, `GET /wiki/pages/{type}/{slug}`, `PATCH`, `DELETE`
- `wiki_writer` with synchronous git commit to the wiki clone
- `index_writer` and `log_writer` (same commit)
- Background push task on configured interval
- Tests: write a page, verify git commit in the clone, verify `index.md` and `log.md` updated, verify the commit is pushed on the next tick

**Exit criteria**: an end-to-end test can write a page via REST and see it land in the wiki remote on the next push cycle.

### Phase 4 — Search (BM25 only, no embeddings)

- Tantivy index setup
- `GET /wiki/search?mode=bm25` returning results
- Incremental indexing on every wiki write
- Tests: write pages, search, verify rankings

**Exit criteria**: search returns relevant results at p95 latency under 30ms.

### Phase 5 — Search (vector + hybrid)

- LanceDB integration
- Embedding with `BGE-small-en-v1.5` (already cached in Docker image)
- `GET /wiki/search?mode=vector` and `?mode=hybrid` (RRF fusion)
- Tests: semantic similarity queries return relevant results
- Benchmark: p95 latency under 60ms at 10K pages

**Exit criteria**: hybrid search is live, latency target met.

### Phase 6 — Auth and RBAC

- Phantom token issuance via `POST /admin/enroll`
- HMAC signing/verification middleware
- Cerbos client + policy file
- Deny-by-default on Cerbos failure
- Tests: auth happy paths, failure paths, policy enforcement

**Exit criteria**: unauthenticated requests fail; unauthorized requests fail; valid requests succeed.

### Phase 7 — Distillation worker (rule-based first)

- JSONL queue
- Background asyncio worker
- Rule-based extractor (regex + heading patterns)
- `POST /distill/session`, `POST /ingest/source`, `GET /jobs/{job_id}`
- Tests: ingest a source, verify pages created, verify idempotency

**Exit criteria**: rule-based distillation produces valid wiki pages for a known test corpus.

### Phase 8 — Distillation worker (LLM-backed)

- LLM extractor with `gpt-4o-mini`
- Configurable via env var (`COMMANDCLAW_MEMORY_DISTILL_MODEL`)
- Prompt library in `distill/prompts.py` that embeds the wiki's `AGENTS.md` schema reference as context
- Tests: extraction accuracy against a fixture corpus
- Cost guardrails: per-job token budget, fallback to rule-based on budget exceeded

**Exit criteria**: LLM-backed distillation produces higher-quality pages than rule-based; cost per ingest is within budget.

### Phase 9 — Agent integration

- `MemoryServiceStore` shim in `commandclaw`
- Four new wiki tools (`wiki_search`, `wiki_read`, `wiki_ingest`, `wiki_lint`)
- `commandclaw-vault/AGENTS.md` template update teaching agents how to use the memory service
- Runtime wiring in `commandclaw/src/commandclaw/agent/graph.py`
- Graceful degradation path
- Tests: end-to-end agent → memory service → wiki repo roundtrip. Includes a test that a fresh agent with no vault mods can `wiki_ingest` a URL and then `wiki_search` for it successfully.

**Exit criteria**: a spawned agent can ingest a source, query the wiki, and get cross-linked results. Kill the memory service, verify the agent enters degraded mode, restart the memory service, verify recovery.

### Phase 10 — Bootstrap from existing vaults

- `POST /admin/bootstrap` endpoint
- `bootstrap/seed_from_vaults.py` — reads `memory/*.md` and optionally `MEMORY.md` from listed vault paths, submits each to the ingest pipeline
- Idempotency tests
- Rollback test (force-push, reindex)
- Document the bootstrap procedure in this PLAN.md if anything changes during implementation

**Exit criteria**: bootstrap runs cleanly against a seeded test fixture of one or more vaults; all surviving daily notes are represented as source pages with linked entity/concept pages.

### Phase 11 — Observability and production readiness

- Langfuse tracing for all endpoints
- Prometheus metrics
- Structured logging
- docker-compose integration with existing mcp stack
- Load test: sustained 100 writes/sec, 1000 searches/sec
- Failure test: kill service mid-write, verify consistency; simulate network partition during `git push`, verify backlog drains on recovery
- 24-hour soak with synthetic load

**Exit criteria**: the service can run unattended for 24 hours under synthetic load without data loss, index divergence, or memory leaks. No unpushed-commit accumulation. No wiki repo divergence.

---

## 14. Open questions

Items that need a decision before or during implementation. Grouped by phase.

**Phase 0 (schema)**

1. Are the four page types (source, entity, concept, synthesis) the right set, or do we need more (e.g., `decision`, `incident`, `session-summary`)?
2. Should `log.md` be a single file or rotated (`log/YYYY-MM.md`)? Karpathy's PRD uses single file; at long horizons this grows unbounded.
3. Do we need per-page content-hash deduplication, or is slug-based identity sufficient?

**Phase 1 (wiki repo + viewers)**

4. Is the wiki repo hosted on GitHub under `FnSK4R17s/commandclaw-wiki`, or is it self-hosted (Gitea, etc.) from day one? For v1 GitHub is simpler and matches the other repos.
5. One shared wiki per deployment, or one wiki per "project" (multi-tenant)? V1 is one shared wiki per deployment; multi-tenant is deferred.
6. Is the `_seed/` directory pre-filled with content derived from the existing CommandClaw whitepapers, or left as placeholder examples? Pre-filling gives immediate signal but couples the seed to current project state.
7. Where is the Quartz site published — public GitHub Pages, GitHub Pages with org access restrictions, or behind Cloudflare Access / Tailscale Funnel? V1 we'd default to public for the first iteration since the wiki content is not sensitive yet, but enterprise deployments will want at least org-restricted.
8. Does the Quartz theme stay as the default Quartz "personal knowledge garden" look, or get reskinned to match a more docs-feeling enterprise look? Affects polish, not function.

**Phase 3 (wiki CRUD + git writer)**

9. Git commit granularity: one commit per wiki write, or batched every N writes? Per-write is simpler, gives clean audit, but makes `log.md` and the git history noisy. Batched improves readability but complicates rollback.
10. What's the push interval default — 60s, 300s, or on-demand only? Frequent pushes are more durable but noisier to the remote; infrequent pushes accumulate risk if the service dies.
11. How do we detect and recover from wiki-repo divergence between the memory service clone and the remote? For v1 the plan is "merge commit on push conflict, 503 on merge conflict" — is that acceptable?

**Phase 5 (vector + hybrid search)**

12. Which BGE variant for the distillation path — small-en-v1.5 (fast, less accurate) or M3 (slower, more accurate)? Beary recommends small-en for hot path, M3 for distill. Both are cached.

**Phase 6 (auth and RBAC)**

13. Does the memory service share the Cerbos instance with `commandclaw-mcp`, or run its own? Shared is simpler but couples failure domains.
14. How does agent enrollment interact with `spawn-agent.sh`? Today, a new agent is not auto-enrolled in `commandclaw-mcp`. Do we want to fix both at once, or keep it manual for now?

**Phase 8 (LLM distillation)**

15. Does the distillation LLM run inside the memory service process, or as a separate worker container? Same-process is simpler; separate is more secure and limits blast radius.
16. Do we need a kill-switch for the distillation LLM (e.g., budget-based)? What's the budget?

**Phase 9 (agent integration)**

17. How do agent sessions signal "end" to trigger distillation? Today, there's no explicit session-end. Does the agent need a new state node, or can we use Telegram `/done` + timeout?

**Phase 10 (bootstrap)**

18. Should `/admin/bootstrap` accept a list of vault paths, or auto-discover all vaults under `~/.commandclaw/workspaces/`? Auto-discover is convenient but requires the memory service to know where host vaults live.

**Phase 11 (ops)**

19. Do we put the memory service in the same docker-compose as `commandclaw-mcp`, or a separate one? Same is more cohesive; separate gives clearer boundaries.

---

## 15. What this plan does not cover

Tracked separately so this plan doesn't grow indefinitely.

- **Telegram on LangGraph runtime port** — existing gap, tracked in the last devlog
- **Scheduler/cron** — Week Two vision item, needs its own plan
- **Multi-agent coordination beyond memory sharing** — out of scope
- **Automatic `commandclaw-mcp` agent enrollment in `spawn-agent.sh`** — tracked in devlog followups
- **A fresh round of PLAN.md for Telegram + scheduler** — will come after this one ships

---

## Signoff

This plan is not to be implemented until the following is decided:

- [ ] Page types in section 3 are finalized (open question 1)
- [ ] The `commandclaw-wiki` repo structure (section 3.1) is approved
- [ ] The `commandclaw-memory` repo structure (section 4.1) is approved
- [ ] The wiki reading stack in section 12 (Obsidian + Quartz + CLI) is approved
- [ ] Build phase order in section 13 is approved
- [ ] Open questions 1–11 (phases 0–3) have answers, since they block the first implementable unit of work
- [ ] Shikhar has reviewed and signed off on this document

Open questions for later phases (12–19) can be answered as those phases begin.

---

## Appendix: revision history

- **2026-04-06**: initial draft placed the wiki inside each per-agent vault as a `wiki/` subtree.
- **2026-04-07 (rev 2)**: wiki split into its own repository `commandclaw-wiki`. Rationale: per-agent vault + cross-agent shared knowledge are different concerns, putting them in one repo led to duplication, leaky boundaries, and weaker schema enforcement. The memory service now owns the wiki repo exclusively and never touches per-agent vaults.
- **2026-04-07 (rev 3, this revision)**: added section 12 "Wiki reading and browsing" specifying the read-only viewer stack. Three audiences (operator, stakeholder, CLI), three viewers (Obsidian against the clone, Quartz static site via GitHub Action, REST API + `cclaw wiki` CLI). Phase 1 expanded to include `.obsidian/` and `quartz/` scaffolding plus the publish workflow. Two new open questions about hosting and theming. The reader stack adds zero ops surface to the memory service itself — it is entirely consumer-side.
