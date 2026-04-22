# commandclaw-memory — the recall service

> Discipline layer for the LLM Wiki. Owns the wiki repo, validates writes, indexes content, exposes hybrid retrieval. Built so a cheap/weak primary model can still keep a clean knowledge base.

## Why it exists

The [commandclaw-wiki](commandclaw-wiki.md) is a human-readable, git-native knowledge base maintained by LLMs. That works great when the maintaining LLM is strong and careful. It falls apart when the primary agent is cheap, fast, or distracted — at which point the wiki accumulates malformed pages, orphaned references, and silent contradictions.

`commandclaw-memory` is the service between the agent and the wiki that enforces the contract. Every write is schema-checked. Every commit is atomic. Every search fuses BM25 + vector + RRF. Distillation (the expensive "figure out what this new source means") happens asynchronously off the hot path, so the agent stays responsive.

It is the **discipline layer**. The wiki is still the durable artifact — readable, portable, auditable in git — even if the service is down, replaced, or rewritten.

> **Status: stub.** The repo is scaffolded; implementation is queued per the [MEMORY_PLAN](../guiding_docs/MEMORY_PLAN.md). What follows is the design.

## What it will do

| Capability | How |
|---|---|
| **Owns the wiki repo** | Clones `commandclaw-wiki` on startup. Single-writer. Sync git commit on every successful write, async push on a configurable interval. |
| **Schema enforcement** | Pydantic models per page type (entity / concept / comparison / synthesis / source). Cross-reference validation. Malformed writes rejected at the REST boundary. |
| **Hybrid retrieval** | LanceDB for vectors (BGE-small-en-v1.5), Tantivy for BM25, Reciprocal Rank Fusion. Sub-60ms warm retrieval target on loopback. |
| **Distillation worker** | Async background task. Configurable LLM (default `gpt-4o-mini`) or rule-based fallback. Runs off the hot path. |
| **Auth + RBAC** | Phantom token + HMAC + Cerbos — same pattern as [commandclaw-mcp](commandclaw-mcp.md). |
| **Graceful degradation** | Circuit breaker → hot-tier fallback → offline write buffer. Agents stay responsive when the service is down. |

## Tech stack and why

| Choice | Reason |
|---|---|
| **Python** | Fits the rest of the stack; Pydantic + FastAPI + LanceDB are all first-class Python. |
| **FastAPI** | Async HTTP, OpenAPI, clean dependency injection for auth — matches the MCP gateway. |
| **Pydantic 2** | The schema *is* the contract. Rich validation, JSON-schema export for introspection. |
| **LanceDB** | Embedded vector store — no separate service, Arrow-native, fast cold-start, handles mixed metadata + vectors. |
| **BGE-small-en-v1.5** | Well-studied, MTEB-strong, small enough to run locally. Swap via config. |
| **Tantivy** | Rust-backed full-text index with Python bindings. Fast BM25, local, zero dependencies. |
| **Reciprocal Rank Fusion** | Robust score fusion across heterogeneous rankers. No tuning knob explosion. |
| **GitPython** | The service owns the wiki clone. Atomic commit-per-write is trivial with `repo.index.add + commit`. |
| **Cerbos** | Same policy engine as [commandclaw-mcp](commandclaw-mcp.md) — one policy idiom across the ecosystem. |
| **Circuit breaker pattern** | A memory service down should not block the agent. Fall back to hot tier (recent MEMORY.md), then to a write buffer. |

## Internal architecture (planned)

```
commandclaw-memory/
├── src/commandclaw_memory/
│   ├── api/              FastAPI routes (see "REST API" below)
│   ├── schema/           Pydantic models per page type
│   ├── wiki/             Git clone management, atomic commit, async push
│   ├── index/
│   │   ├── vectors.py    LanceDB writer + reader
│   │   └── bm25.py       Tantivy writer + reader
│   ├── retrieval/        Hybrid query, RRF fusion, reranking hook
│   ├── distill/          Async worker, LLM distillation, rule-based fallback
│   ├── auth/             Phantom token + HMAC validation
│   ├── rbac/             Cerbos client
│   └── degrade/          Circuit breaker, hot-tier cache, offline write buffer
└── policies/             Cerbos policies
```

### Write path

```
POST /wiki/pages {type, slug, body}
    ▼
Auth + RBAC        → phantom token valid? agent permitted to write this type?
    ▼
Schema validator   → Pydantic model for <type>, cross-ref check
    ▼
Wiki writer        → write file, git add, git commit (sync)
    ▼
Indexer            → LanceDB upsert (vector) + Tantivy upsert (BM25)
    ▼
Async push         → queued on a timer; never blocks the response
    ▼
200 OK
```

### Read path

```
GET /wiki/search?q=...
    ▼
Retrieval
  ├─ BM25 (Tantivy)  → top-k candidates
  └─ Vector (LanceDB) → top-k candidates
    ▼
RRF fusion           → merged ranking
    ▼
Hydrate              → load page bodies from disk (files already in memory cache)
    ▼
Response             → ranked list with citations
```

### Distillation path

Runs on its own task loop. Pulls from a queue of "please distill this raw source" or "summarize this session transcript." Writes the result via the same validated write path, so distilled pages go through the exact same discipline as agent-authored ones.

## REST API surface (planned)

```
POST   /wiki/pages                  Create a wiki page (validated, committed, indexed)
GET    /wiki/pages/{type}/{slug}    Read a page
PATCH  /wiki/pages/{type}/{slug}    Update a page
DELETE /wiki/pages/{type}/{slug}    Delete a page (admin/owner only)

GET    /wiki/search                 Hybrid BM25 + vector + RRF
GET    /wiki/index                  index.md as structured JSON

POST   /ingest/source               Trigger distillation of a raw source
POST   /distill/session             Trigger distillation of a session transcript
POST   /lint                        Health-check the wiki (orphans, contradictions)
GET    /jobs/{job_id}               Poll a distillation job

POST   /admin/reindex               Full rebuild from the wiki repo
POST   /admin/wiki/pull             Force-fetch + reset to remote
POST   /admin/wiki/push             Force-push pending commits
POST   /admin/bootstrap             Seed-from-vaults bootstrap
POST   /admin/enroll                Issue agent credentials

GET    /health, /ready, /metrics    Operational
```

## External interfaces

| Interface | Direction | Used for |
|---|---|---|
| **HTTP REST** | [runtime](commandclaw.md) → memory | `wiki_search`, `wiki_read`, `wiki_ingest`, `wiki_lint` tools. |
| **LangGraph `BaseStore` shim** | runtime → memory | `MemoryServiceStore` adapter so LangGraph's built-in store API works. |
| **git** | memory ↔ [commandclaw-wiki](commandclaw-wiki.md) | Pull on startup, commit on write, async push. |
| **Cerbos gRPC** | memory ↔ Cerbos | Policy evaluation. |
| **LLM over HTTP** | memory → [commandclaw-gateway](commandclaw-gateway.md) | Distillation calls go through the same gateway as the agent's LLM calls. |

The agent never touches the wiki repo directly. The memory service never touches per-agent vaults. Clean boundaries on both sides.

## Deployment shape

```yaml
services:
  commandclaw-memory:    # FastAPI, port 8284
  cerbos:                # policy engine
  # persistent volume for: wiki clone, LanceDB files, Tantivy index
```

The only durable state outside git is the index files — and both LanceDB and Tantivy can be rebuilt from the wiki repo via `POST /admin/reindex`. Losing the index is an inconvenience, never data loss.

## Why a service over "let the agent write markdown directly"

| Alternative | Why we didn't |
|---|---|
| **Agent writes to the wiki repo directly** | Cheap models produce malformed frontmatter, orphan wikilinks, contradict earlier pages. No one catches it until the wiki becomes unusable. |
| **A linter cron job** | Catches errors after the fact. Broken pages still get into git. |
| **A "smart" primary agent** | Makes the primary expensive and slow. The whole point is to let primary stay cheap. |
| **Do RAG over `raw/` at query time** | Re-derives synthesis every query. Expensive. No compounding. |

The service lets cheap primaries stay cheap by enforcing discipline at the boundary, and lets expensive distillation happen asynchronously where latency doesn't matter.

## Key documents

- [commandclaw-memory-service whitepaper](https://github.com/FnSK4R17s/commandclaw/blob/main/whitepaper-output/commandclaw-memory-service/whitepaper/commandclaw-memory-service-whitepaper.md) — full ten-dimension spec
- [MEMORY_PLAN.md](../guiding_docs/MEMORY_PLAN.md) — implementation plan
- [MEMORY_PRD_KARPATHY.md](../guiding_docs/MEMORY_PRD_KARPATHY.md) — Karpathy-style PRD
