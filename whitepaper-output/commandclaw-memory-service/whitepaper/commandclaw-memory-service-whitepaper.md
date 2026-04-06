# CommandClaw Memory Service Architecture

<!-- See .agents/skills/beary/skills/whitepaper-writing/SKILL.md for whitepaper writing guidelines. -->

**Author:** Background Research Agent (BEARY)
**Date:** 2026-04-06

---

## Abstract

This whitepaper defines the architecture of `commandclaw-memory`, a dedicated memory service for the CommandClaw agent platform. Building on the prior agent-memory-architecture whitepaper (which established LanceDB, git vault as source of truth, hot/warm/cold tiering, and hybrid BM25+vector retrieval), this paper addresses the question the prior whitepaper deferred: should CommandClaw's memory layer be an embedded library, an MCP server, or a separate microservice? The answer is a **separate HTTP microservice** with a LangGraph `BaseStore`-compatible interface. We validate a five-primitive architectural framing (loop runner, perception bus, effector layer, memory layer, substrate) that correctly identifies vault and memory as two distinct concerns currently conflated in CommandClaw's design. We then specify all ten design dimensions of the service: storage backend (LanceDB, confirmed), sync model (git-first with post-commit hook, derived index), distillation (async background, lightweight LLM), auth (phantom-token + HMAC + Cerbos, consistent with commandclaw-mcp), tenancy (agent_id-scoped with opt-in cross-agent reads), API surface (REST with five core operations), failure modes (circuit breaker → hot-tier fallback → write buffer), RPC latency (sub-60ms warm retrieval on loopback), multi-agent shared knowledge (scoped reads via agent_id), and migration from flat vault files (batch embed, incremental by tier, idempotent via content hash). The result is a service architecture that is independently deployable, consistent with all six existing CommandClaw whitepapers, and implementable on a single machine without Docker registry or cloud infrastructure.

---

## Introduction

The CommandClaw agent-memory-architecture whitepaper [13] answered: *what* should be stored and *how* it should be retrieved. It left open a more fundamental question: *where* does the retrieval happen — inside the agent process, inside the MCP gateway, or in a dedicated service? As CommandClaw moves from a single-agent prototype to a multi-agent platform where BEARY, the main assistant, and future specialized agents each need runtime memory access, the architectural choice becomes load-bearing.

The naive answer — keep it embedded, load vault files into the system prompt — fails at multi-agent scale for two reasons. First, wholesale vault loading into context is O(n) token cost per invocation; as the vault grows it triggers the context-obesity failure mode the prior whitepaper warned against [13]. Second, when multiple agents are active concurrently, each reads its own snapshot of the vault. Memories written by one agent in session are invisible to another until the next vault reload. This is not a consistency model; it is a consistency illusion.

This whitepaper makes the case for a dedicated `commandclaw-memory` service — a small, independently-deployed FastAPI process that sits alongside `commandclaw-mcp` in the CommandClaw process graph, provides a REST API for memory read/write/search operations, owns the LanceDB vector index, manages the distillation pipeline, and is backed by (but does not replace) the git vault as cold-tier source of truth.

The paper is organized as follows: Section 2 validates the five-primitive framing against academic and platform evidence. Section 3 makes the service-vs-embedded decision with explicit trade-off analysis. Sections 4–13 address the ten design dimensions in detail. Section 14 gives the complete API surface. Section 15 summarizes the migration path from the current design.

---

## Section 2: The Five-Primitive Agent Architecture Framing

### 2.1 The Proposed Primitives

CommandClaw's architecture can be decomposed into five functional primitives:

1. **Loop Runner** — the LangGraph StateGraph that executes the agent cognitive cycle (PERCEIVE→THINK→ACT→REMEMBER)
2. **Perception Bus** — the input processing layer: message ingestion, NeMo Guardrails input rails, session classification
3. **Effector Layer** — the commandclaw-mcp gateway, native Python tools, and any direct API calls the agent can make
4. **Memory Layer** — the runtime-queryable, semantically indexed store of agent knowledge, accessible in sub-100ms during a live session
5. **Substrate** — the git vault: configuration source of truth, cold-tier memory archive, audit trail, human-readable control plane

The central claim is that **memory layer (4) and substrate (5) are two distinct concerns**. The current CommandClaw design conflates them by loading vault Markdown files into the system prompt — treating the substrate as if it were the memory layer. This creates a retrieval system that is O(n) in vault size, stale by the age of the last vault snapshot, and not queryable by semantic similarity.

### 2.2 Academic Validation

The strongest academic support comes from a 2026 arXiv survey on agent memory mechanisms [5], which frames agent cognition as a POMDP with four irreducible functions: Perception (Φ), Memory Update (μ), Cognitive Planning (Ψ), and Action Policy (π). These map directly onto the five primitives: Φ = perception bus, μ = memory layer, Ψ = loop runner, π = effector layer. The "substrate" is not a cognitive function in the POMDP framing — it is correctly the persistence layer *external* to the cognitive loop, added by distributed systems design for auditability and human control.

SOAR's cognitive architecture provides further validation [17]. SOAR decomposes agent cognition into: working memory (current problem state), semantic memory (long-term declarative facts), episodic memory (experience replay), and production memory (long-term procedural rules). This maps onto CommandClaw's tiers: working memory = hot tier (MEMORY.md in context), semantic/episodic memory = warm tier (LanceDB index), production memory = substrate (agent skills and policies in the vault). SOAR does not conflate its memory tiers; CommandClaw should not either.

### 2.3 Platform Validation

A survey of six agent platforms confirms the framing:

| Platform | Loop Primitive | Memory Primitive | Explicit Substrate? |
|----------|---------------|-----------------|---------------------|
| LangGraph | StateGraph nodes/edges | BaseStore + checkpointer | No |
| Letta/MemGPT | Agent event loop | Core/Recall/Archival tiers | No |
| Mem0 | External (any) | add()/search() service | No |
| Mastra | Workflow + Agent | agent.memory (MemoryProcessor) | No |
| AutoGen | Actor message loop | Message history (implicit) | No |
| smolagents | While loop (CodeAgent) | (code, observation) pairs (implicit) | No |

No external platform has an explicit substrate primitive — they leave it to the deployment environment. CommandClaw is unique in making the git vault a first-class primitive because it serves a dual purpose: configuration management (agent skills, system prompts, user profiles) and cold-tier memory archive. This is a correct design decision for a platform where human inspectability and auditability are first-class requirements.

**Verdict: The five-primitive framing is correct, not contradicted by any surveyed platform, and provides the right conceptual basis for the service split decision.**

### 2.4 The "Substrate" Dual Role

The vault serves two distinct roles: (a) **configuration/policy** — agent skills, system prompts, user profiles, Cerbos policies, all read at agent startup; and (b) **cold-tier memory** — archived session summaries and superseded facts, written by agents over time. These roles are logically separable but practically unified at CommandClaw's current scale (one developer, dozens of agents). The five-primitive model correctly treats both as substrate, with a clear upgrade path to split them into a separate config store when the operational complexity justifies it.

---

## Section 3: Service vs. Embedded — The Decision

### 3.1 Options Considered

Four deployment patterns were evaluated:

**Option A: Embedded library** — `commandclaw-memory` is a Python package imported directly by each agent process. LanceDB and the distillation pipeline run inside the agent process.

**Option B: MCP server** — memory operations are exposed as MCP tools (`retain`, `recall`, `reflect`), callable via the existing commandclaw-mcp gateway using the established httpx JSON-RPC pattern [9].

**Option C: Dedicated HTTP microservice** — a standalone FastAPI process running on a fixed port (e.g., 8284), providing a REST API for memory read/write/search, independent of the agent runtime.

**Option D: LangGraph BaseStore replacement** — implement a custom `BaseStore` subclass that routes `asearch`/`aput`/`aget` calls to a local LanceDB instance, replacing the current in-memory/Postgres store.

### 3.2 Analysis

**Option A (embedded library)** fails at multi-agent scale because LanceDB's embedded mode does not support concurrent writes from multiple processes (it uses file-level locking). If two agents write memories simultaneously, one will block or error. Additionally, each agent process would hold its own LanceDB file handles and embedding model weights in memory, multiplying RAM usage with agent count.

**Option B (MCP server)** is architecturally elegant — it fits the established tool-use paradigm and reuses the phantom-token + HMAC auth pattern from commandclaw-mcp [9]. The `retain`/`recall`/`reflect` tool pattern used by Hindsight is clean. The constraint: per the mcp-langgraph-integration whitepaper, CommandClaw must use raw httpx JSON-RPC to avoid the anyio conflict [9]. This means every memory operation is a full HTTP round-trip through the MCP gateway — two hops (agent → gateway → memory server) instead of one. On loopback this adds <5ms, which is acceptable, but the MCP gateway becomes a single point of failure for both tool execution and memory access, coupling two critical paths.

**Option C (dedicated HTTP microservice)** decouples memory from the MCP gateway. Agents make direct HTTP calls to the memory service — one hop. The service is independently deployable, restartable, and upgradeable without touching the MCP gateway. Auth is applied at the memory service level using the same phantom-token + HMAC pattern. This is the pattern used by Letta (FastAPI on port 8283), Mem0 (embedded or hosted service), and Zep (standalone process).

**Option D (BaseStore replacement)** is the lowest-friction integration path for LangGraph — it slots into the existing `runtime.store.asearch/aput` interface without changing agent code. However, it embeds the vector store inside the LangGraph process, recreating the Option A concurrency problem. LangMem uses this pattern but documents that `InMemoryStore` is dev-only and `AsyncPostgresStore` should be used in production — which is not a vector store.

### 3.3 Decision: Option C with Option D as the LangGraph interface shim

The architecture is:
- **Core**: A FastAPI HTTP microservice (`commandclaw-memory`) running on port 8284, owning LanceDB, managing the distillation pipeline, and enforcing auth via phantom-token + HMAC + Cerbos.
- **LangGraph shim**: A thin `MemoryServiceStore` class implementing LangGraph's `BaseStore` interface, making HTTP calls to the memory service. This allows agent code to use the familiar `store.asearch()`/`store.aput()` pattern without knowing the implementation is a separate process.
- **Optional MCP surface**: The MCP gateway can expose `retain`/`recall` as forwarding tools that call the memory service REST API, making memory accessible to agents that prefer tool-use over direct store access. This is additive, not required.

This architecture provides: (1) process isolation between agent runtime and memory service, (2) single LanceDB writer (no concurrency conflict), (3) independent restart/upgrade, (4) shared memory across all agents (single service, not per-agent), (5) consistent auth via existing patterns.

---

## Section 4: Storage Backend

**Decision: LanceDB (confirmed)**

The prior whitepaper's recommendation [13] is confirmed and extended. LanceDB's January 2026 updates now report 1.5M IOPS via io_uring and sub-25ms vector search latency on GIST-1M — well within the sub-60ms hot-path target for warm retrieval. LanceDB remains the only embedded vector store that provides: zero-dependency operation (no separate process), Python-native API, Lance columnar format for disk efficiency, IVF_PQ indexing for sub-60ms ANN at 1M vectors, and a supported asyncio interface (`await table.vector_search()`).

Qdrant remains the alternative if multi-machine deployment or advanced filtering is ever needed, but at single-machine scale its 400MB constant RAM overhead and separate process management are not justified. pgvector remains useful as the checkpointer backend (PostgresSaver [11]) but its 80–150ms vector query latency makes it unsuitable for hot-path memory retrieval.

**Storage layout within the service:**

```
~/.commandclaw/memory/
  lancedb/
    memories/          # Main memory table (LanceDB)
    memories.ivf_pq/   # Trained index
  queue/
    pending_distill/   # Async distillation queue (append-only JSONL)
  bm25/
    memories.bm25      # Tantivy BM25 index (for hybrid retrieval)
```

The LanceDB directory is the derived index — always rebuildable from the git vault. The distillation queue and BM25 index are also derived. Nothing in `~/.commandclaw/memory/` is the source of truth; the git vault is.

---

## Section 5: Sync Model — Git-First, Derived Index

**Decision: Git commit is primary; vector index is derived; sync is async post-commit.**

The correct consistency model for CommandClaw is: **the git vault is the authoritative source of truth, and the vector index is a derived artifact that can always be rebuilt from it.** This is identical to how the prior whitepaper treats LanceDB — as a rebuildable cache, not a primary store [13].

The sync pipeline:

1. **Agent writes a memory** → calls `POST /memories` on the memory service
2. **Memory service writes to LanceDB** (immediate, synchronous, returned in the response)
3. **Memory service writes the raw Markdown representation to the vault** via a git commit (synchronous, completes before response returns)
4. **Post-commit hook triggers async re-indexing** of any changed files (background, non-blocking)
5. **Stale-but-consistent reads** are served from LanceDB during re-indexing

The critical design choice: **step 3 (git commit) happens synchronously before the HTTP response returns.** This ensures that if the memory service crashes after acknowledging the write, the memory is still persisted in git. LanceDB is the fast read cache; git is the write-ahead log.

**On vault divergence recovery:** If LanceDB diverges from the vault (crash during write, partial failure), the recovery procedure is: (1) detect divergence via a periodic health check that compares LanceDB record count to vault file count; (2) trigger a full re-index from vault sources. This is the same recovery procedure as any derived index.

**Post-commit hook implementation:**

```bash
#!/bin/bash
# .git/hooks/post-commit
# Trigger async memory re-indexing for changed vault files
changed=$(git diff-tree --no-commit-id -r --name-only HEAD)
echo "$changed" >> ~/.commandclaw/memory/queue/pending_reindex.txt
# Signal the memory service background worker (non-blocking)
kill -USR1 $(cat ~/.commandclaw/memory/service.pid) 2>/dev/null || true
```

The memory service runs a background asyncio task that watches the pending_reindex.txt file and processes changed files in batches.

**DiffMem note:** DiffMem's approach of using Git as the sole memory store (no vector index) was evaluated [from research]. It is a viable proof-of-concept but lacks ANN indexing, has no semantic similarity retrieval, and rebuilds its index on every initialization — not suitable for production use. The CommandClaw approach (git as source of truth, LanceDB as derived index) takes DiffMem's correct insight (git is the honest memory) while preserving fast semantic retrieval.

---

## Section 6: Distillation

**Decision: Async background, lightweight extraction, BGE-small-en-v1.5 for embeddings.**

"Distillation" refers to the pipeline that takes raw conversation content (agent messages, tool outputs, session summaries) and produces structured, searchable memory entries. The question is: who triggers it, what model runs it, and is it synchronous or async?

**Trigger:** Distillation is triggered at session end, not continuously. When an agent session concludes, the agent sends a `POST /sessions/{session_id}/distill` request to the memory service. The memory service accepts the request immediately (202 Accepted) and enqueues the distillation job.

**Model:** BGE-small-en-v1.5 (already cached) for embedding. For fact extraction (identifying what in the session transcript deserves to become a durable memory entry), a lightweight LLM call using the OpenAI API with a small model (e.g., gpt-4o-mini) at low cost — or, for fully local operation, a rule-based extractor that identifies structured content (decisions, facts, action items) via regex and heading patterns.

**Synchrony:** Async background. The distillation worker runs in a separate asyncio task inside the memory service process. It does not block the main FastAPI event loop. The agent does not wait for distillation to complete before terminating the session.

**Distillation pipeline:**

```
Raw session content
  → Chunking (512-token chunks, 50-token overlap)
  → Fact extraction (LLM or rule-based)
  → Deduplication (content hash against existing memories)
  → Embedding (BGE-small-en-v1.5, 384d)
  → Write to LanceDB (warm tier)
  → Summarize for cold archive
  → Commit to git vault (cold tier)
```

**Why not Letta's context-pressure-triggered approach?** Letta distills when the context window fills — this is reactive and blocks the agent. CommandClaw's distillation is proactive and async, matching Mem0's and Zep's model. The agent never blocks on distillation.

**Why not Cognee's synchronous approach?** Cognee's `cognify()` is synchronous — the caller waits for the full graph construction pipeline. At session-end with potentially thousands of tokens of session content, this would add unacceptable latency to session cleanup.

---

## Section 7: Authentication

**Decision: Phantom-token + HMAC + Cerbos RBAC, identical to commandclaw-mcp pattern.**

The auth model from the commandclaw-mcp whitepaper [9] transfers directly to the memory service with no modifications needed:

**Phantom-token pattern:** The memory service issues opaque service tokens to each caller (agent process). Agents include their token in every request. The memory service resolves the token to an internal principal identity (agent_id + role). The real credentials (LanceDB path, vault path) never leave the service.

**HMAC request signing:** Every request carries an HMAC signature over: `method + path + timestamp + nonce + SHA-256(body)`. The signing key is a `secrets.token_urlsafe(32)` per-service secret shared at startup via environment variable. The memory service verifies the signature before processing any request. This prevents replay attacks and request tampering on loopback.

**Cerbos RBAC:** Access policies are evaluated by the existing Cerbos instance. Example policies:
- `BEARY` agent: can read/write own memories, can read `shared` namespace memories, cannot delete
- `main-assistant` agent: can read/write own memories, can read BEARY memories (for research results), cannot delete
- `admin` role: full read/write/delete across all namespaces

**Development mode:** `MEMORY_AUTH_DISABLED=true` bypasses all auth and HMAC checks, consistent with commandclaw-mcp's development mode.

**Why not mTLS?** mTLS requires certificate management (CA setup, cert rotation, key storage). On a single machine with loopback communication, the overhead is unjustified. Phantom-token + HMAC provides equivalent request integrity without certificate infrastructure [20].

---

## Section 8: Tenancy Model

**Decision: agent_id-scoped writes, configurable cross-agent reads via namespace.**

Every memory entry is tagged with the writing `agent_id`. By default, an agent can only read its own memories (`agent_id` filter applied to every retrieval query). Cross-agent reads are enabled by explicit namespace configuration.

**Namespace design:**

```
private/                  # Agent-private memories (agent_id-scoped)
  beary/                  # BEARY's private memories
  main-assistant/         # Main assistant's private memories
shared/                   # Cross-agent shared memories
  research/               # BEARY research outputs (readable by all)
  decisions/              # Project decisions (readable by all)
  project-state/          # Current project state (readable by all)
```

Agents write to their private namespace by default. Agents can promote a memory to the shared namespace explicitly (subject to Cerbos policy). Agents can read from the shared namespace by specifying `namespace=shared` in retrieval queries.

**Letta comparison:** Letta's tenancy model is agent_id-scoped with no native cross-agent sharing in the open-source version — cross-agent memory requires a dedicated "memory agent" that others query [6]. CommandClaw's namespace model is simpler and more direct.

**Multi-agent shared knowledge:** The `shared/research/` namespace solves the concrete use case where BEARY produces a whitepaper and the main assistant needs to access the research findings. BEARY writes findings to `shared/research/`; the main assistant retrieves from that namespace during planning.

---

## Section 9: API Surface

The memory service exposes five core REST operations:

```
POST   /memories                    # Write a new memory entry
GET    /memories/search             # Semantic + BM25 hybrid search
GET    /memories/{memory_id}        # Get a specific memory by ID
DELETE /memories/{memory_id}        # Delete a memory (admin or owner only)
POST   /sessions/{session_id}/distill  # Trigger async session distillation
```

Additionally, four operational endpoints:

```
GET    /health                      # Health check (LanceDB, vault, distill queue)
GET    /metrics                     # Langfuse-compatible metrics (write rate, search latency, queue depth)
POST   /admin/reindex               # Trigger full re-index from vault (admin only)
GET    /admin/stats                 # Memory counts by agent_id and namespace
```

**Request/response shapes (representative):**

`POST /memories` body:
```json
{
  "agent_id": "beary",
  "namespace": "private",
  "content": "The five-primitive framing is validated by SOAR and ACT-R academic architectures.",
  "content_type": "fact",
  "source": "session:2026-04-06-research",
  "tags": ["architecture", "five-primitive", "validated"]
}
```

`GET /memories/search` params:
```
?query=agent+architecture+primitives
&agent_id=beary
&namespace=private,shared/research
&limit=10
&mode=hybrid
```

Response:
```json
{
  "results": [
    {
      "memory_id": "mem_abc123",
      "content": "The five-primitive framing is validated...",
      "score": 0.94,
      "agent_id": "beary",
      "namespace": "private",
      "created_at": "2026-04-06T14:22:11Z",
      "source": "session:2026-04-06-research"
    }
  ],
  "search_latency_ms": 42
}
```

**LangGraph BaseStore shim:** The `MemoryServiceStore` class implements `BaseStore.asearch()` / `BaseStore.aput()` / `BaseStore.aget()` by translating LangGraph's tuple-based namespace scheme to the REST API. This allows agent code to remain unchanged while the backing store is the memory service.

```python
class MemoryServiceStore(BaseStore):
    def __init__(self, base_url: str, token: str, hmac_key: str):
        self._base_url = base_url
        self._token = token
        self._hmac_key = hmac_key

    async def asearch(self, namespace: tuple[str, ...], /, query: str, limit: int = 10):
        ns = "/".join(namespace)
        response = await self._signed_get(f"/memories/search?namespace={ns}&query={query}&limit={limit}")
        return [Item(value=r["content"], key=r["memory_id"], namespace=namespace) for r in response["results"]]

    async def aput(self, namespace: tuple[str, ...], key: str, value: dict):
        ns = "/".join(namespace)
        await self._signed_post("/memories", {"namespace": ns, "memory_id": key, **value})
```

---

## Section 10: Failure Modes and Graceful Degradation

**Decision: Circuit breaker → hot-tier fallback → local write buffer → vault keyword fallback.**

The memory service is not on the critical path for agent *responsiveness* — an agent can still converse using only its hot-tier context (MEMORY.md loaded at session start). However, it is on the critical path for *memory continuity* — without the memory service, new memories cannot be written and warm-tier memories cannot be retrieved.

**Degradation sequence:**

1. **Health check at session start**: The agent (or LangGraph state machine) calls `GET /health` on the memory service before the session begins. If the health check fails:
2. **Circuit breaker opens**: The `MemoryServiceStore` shim switches to degraded mode. All `asearch()` calls return empty results (instead of raising). All `aput()` calls buffer to a local JSONL file (`~/.commandclaw/memory/queue/offline_writes.jsonl`).
3. **Hot tier only**: The agent continues the session using MEMORY.md context only. A degradation notice is appended to the system prompt: "Memory service unavailable. Operating on hot-tier context only."
4. **Vault keyword fallback**: If the agent explicitly requests memory retrieval (e.g., "what do I know about X?"), the fallback implementation runs a grep over vault Markdown files. This is slow (1–5 seconds) but available.
5. **On reconnection**: When the memory service comes back up, the `offline_writes.jsonl` buffer is replayed in order, then cleared.

**This pattern mirrors commandclaw-mcp's degradation pattern** [9] — the MCP gateway also has a circuit breaker that falls back to native Python tools when the gateway is unavailable.

**Langfuse tracing**: All memory service calls (success, failure, fallback activation) are traced to Langfuse with `memory_service_health`, `memory_search_latency_ms`, and `fallback_activated` spans. This provides operational visibility without adding monitoring infrastructure.

---

## Section 11: RPC Latency on the Hot Memory Path

**Target: sub-60ms round-trip for warm retrieval on loopback.**

The hot memory path is: agent sends `GET /memories/search` → memory service performs hybrid BM25+vector search → returns results. On loopback (localhost:8284), network overhead is <1ms. The bottleneck is the vector search itself.

**Latency budget breakdown:**

| Operation | Estimated Latency |
|-----------|------------------|
| Loopback HTTP overhead | <1ms |
| Request HMAC verification | <1ms |
| BM25 search (Tantivy, 100K chunks) | 5–15ms |
| Vector search (LanceDB IVF_PQ, 100K vectors, BGE-small 384d) | 15–30ms |
| RRF fusion | <1ms |
| Cerbos policy check | 5–10ms |
| Response serialization | <1ms |
| **Total** | **~27–58ms** |

This is within the sub-60ms target. At 1M vectors (multi-year memory horizon), LanceDB's IVF_PQ latency rises to ~40–60ms — still within target. BGE-small-en-v1.5 (384 dimensions) is chosen over BGE-M3 (1024 dimensions) specifically for the hot-path latency advantage: smaller embeddings search faster, and at CommandClaw's corpus size the quality difference is marginal.

**Cold path (distillation, re-indexing) is explicitly off the hot path.** These operations run in background asyncio tasks and do not affect search latency.

---

## Section 12: Multi-Agent Shared Knowledge

**Decision: Shared namespace with explicit promotion, not automatic cross-agent visibility.**

The risk of automatic cross-agent memory sharing is semantic pollution: BEARY's research notes are written for a different audience and purpose than the main assistant's action plans. Automatic sharing would make the main assistant's warm-tier retrieval noisier.

**The controlled sharing model:**

1. An agent promotes a memory to `shared/` by specifying `namespace: "shared/research"` in the write request (subject to Cerbos policy).
2. Other agents read from `shared/` by including it in the `namespace` parameter of search requests.
3. The shared namespace is readable by all agents but writable only by the originating agent or an admin role.

This is analogous to the Unix permission model: agent-private memories are mode 600 (owner read/write only); shared memories are mode 644 (owner write, all read).

**Letta's context repositories pattern** (git worktrees for per-agent memory isolation) [14] is complementary: it provides worktree isolation at the vault level for concurrent writes. CommandClaw's implementation reuses this pattern: each agent session gets its own git worktree for vault writes, and post-merge hooks trigger re-indexing into the shared LanceDB instance.

---

## Section 13: Migration from Flat Vault Files

**Decision: Batch embed, incremental by tier, idempotent via content hash.**

The current state: all agent memories live as Markdown files in the vault, loaded wholesale into the system prompt. The migration goal: move warm-tier memories into the LanceDB index so they can be retrieved on demand rather than loaded unconditionally.

**Migration pipeline (one-time batch job):**

```python
# migration/bootstrap_memory_service.py

TIER_ORDER = [
    ("MEMORY.md", "hot_tier_source"),    # Highest priority
    ("memory/*.md", "warm_tier"),         # Second
    ("archive/*.md", "cold_tier"),        # Last
]

for glob_pattern, content_type in TIER_ORDER:
    for path in vault_root.glob(glob_pattern):
        chunks = chunk_markdown(path, chunk_size=512, overlap=50)
        for i, chunk in enumerate(chunks):
            content_hash = sha256(chunk.encode()).hexdigest()
            if memory_service.exists(content_hash=content_hash):
                continue  # Idempotent: skip already-indexed chunks
            memory_service.write(
                content=chunk,
                content_hash=content_hash,
                source_file=str(path.relative_to(vault_root)),
                chunk_index=i,
                content_type=content_type,
                agent_id="migration",
                namespace="shared/vault-bootstrap"
            )
```

**Estimated migration time:** A typical CommandClaw vault (hundreds of Markdown files, ~50K tokens total) produces approximately 5,000–10,000 chunks. BGE-small-en-v1.5 embeds at ~500 chunks/second on CPU, giving a total migration time of 10–20 seconds. The migration can be interrupted and re-run safely (idempotent via content hash).

**After migration:** MEMORY.md continues to be loaded into the system prompt as the hot tier (unchanged). The `memory/*.md` files are no longer loaded unconditionally; instead, the agent issues `store.asearch()` calls during the session when it needs warm-tier context. The `archive/*.md` files remain git-searchable for cold retrieval.

**Net effect on token cost:** An agent that previously loaded 10,000 tokens of vault context unconditionally will now load ~2,000 tokens of hot tier (MEMORY.md) plus ~500 tokens of retrieved warm-tier memories (top-5 chunks from hybrid search). This is approximately an 80% reduction in per-session memory token cost.

---

## Section 14: Complete Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     CommandClaw Process Graph                   │
│                                                                 │
│  ┌─────────────────┐     ┌─────────────────┐                   │
│  │  Agent Process  │     │  Agent Process  │  (per agent)      │
│  │  (LangGraph)    │     │  (LangGraph)    │                   │
│  │                 │     │                 │                   │
│  │ MemoryService   │     │ MemoryService   │                   │
│  │ Store (shim)    │     │ Store (shim)    │                   │
│  └────────┬────────┘     └────────┬────────┘                   │
│           │  HTTP (loopback)      │                            │
│           └──────────┬────────────┘                            │
│                      │                                         │
│           ┌──────────▼──────────────┐                         │
│           │  commandclaw-memory     │  port 8284               │
│           │  (FastAPI)              │                          │
│           │                         │                          │
│           │  ┌─────────────────┐   │                          │
│           │  │  LanceDB        │   │  ~/.commandclaw/memory/  │
│           │  │  (warm index)   │   │                          │
│           │  └─────────────────┘   │                          │
│           │  ┌─────────────────┐   │                          │
│           │  │  BM25 (Tantivy) │   │                          │
│           │  └─────────────────┘   │                          │
│           │  ┌─────────────────┐   │                          │
│           │  │  Distill Queue  │   │                          │
│           │  └─────────────────┘   │                          │
│           │  ┌─────────────────┐   │                          │
│           │  │  Cerbos client  │   │                          │
│           │  └─────────────────┘   │                          │
│           └──────────┬─────────────┘                          │
│                      │ git commit (sync write)                 │
│                      │ post-commit hook (async reindex)        │
│                      ▼                                         │
│           ┌──────────────────────┐                            │
│           │   commandclaw-vault  │  (git repository)          │
│           │   (substrate)        │                            │
│           │                      │                            │
│           │  MEMORY.md (hot)     │                            │
│           │  memory/*.md (warm)  │                            │
│           │  archive/*.md (cold) │                            │
│           └──────────────────────┘                            │
│                                                                 │
│  ┌──────────────────────────────┐                             │
│  │  commandclaw-mcp (port 8283) │  (separate, unchanged)      │
│  │  optional: retain/recall     │  forwards to port 8284      │
│  │  MCP tools                   │                             │
│  └──────────────────────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Design Recommendations

### Ten Design Dimensions — Summary

| Dimension | Decision |
|-----------|----------|
| Storage backend | LanceDB (embedded, warm tier); git vault (cold tier, source of truth) |
| Sync model | Git-first (commit synchronous, LanceDB async derived); post-commit hook triggers re-index |
| Distillation | Async background; triggered at session end; BGE-small-en-v1.5 for embeddings; gpt-4o-mini or rule-based for fact extraction |
| Auth | Phantom-token + HMAC request signing + Cerbos RBAC; mirrors commandclaw-mcp exactly |
| Tenancy | agent_id-scoped writes; namespace-based cross-agent reads; private/shared namespace hierarchy |
| API surface | REST (5 core + 4 operational endpoints); LangGraph BaseStore shim; optional MCP forwarding |
| Failure modes | Circuit breaker → hot-tier only → offline write buffer → vault keyword fallback |
| RPC latency | Sub-60ms warm retrieval on loopback (27–58ms estimated budget breakdown) |
| Multi-agent shared knowledge | Explicit namespace promotion (shared/research/, shared/decisions/); Cerbos governs promotion |
| Migration | Batch embed by tier (hot→warm→cold), idempotent via SHA-256 content hash, ~10–20s for typical vault |

### Key Invariants

These invariants must be maintained across any future refactoring:

1. **Git vault is the source of truth.** The LanceDB index is always derivable from the vault. If they diverge, the vault wins.
2. **Memory writes are synchronous to git; async to LanceDB.** The git commit completes before the HTTP response returns. LanceDB updates are eventual.
3. **The memory service is the sole writer to LanceDB.** No agent process writes to LanceDB directly. All writes go through the service's REST API.
4. **Agent code uses the BaseStore shim.** Agent code should not import LanceDB, should not know the memory service port, and should not construct HTTP clients directly. These are implementation details of `MemoryServiceStore`.
5. **Auth is never disabled in production.** `MEMORY_AUTH_DISABLED=true` is only valid in development mode (enforced by checking `ENVIRONMENT=development`).

---

## Discussion

### What This Changes vs. the Prior Whitepaper

The agent-memory-architecture whitepaper [13] recommended: LanceDB for vector storage, git vault as source of truth, hot/warm/cold tiering, hybrid BM25+vector retrieval. This whitepaper confirms all four recommendations and adds the service layer on top. Nothing in the prior whitepaper is contradicted; the prior whitepaper described *what* to store and *how* to retrieve it; this whitepaper describes *where* retrieval happens and *who* manages it.

The one addition is the distinction between BGE-M3 (recommended for embedding quality in the prior whitepaper) and BGE-small-en-v1.5 (recommended for hot-path latency here). Both are pre-cached. The recommendation is to use BGE-small-en-v1.5 for real-time retrieval (sub-60ms requirement) and BGE-M3 for batch distillation (no latency requirement, higher quality). This is not a contradiction but a refinement: use the right model for the right job.

### The Anyio Constraint and the MCP Option

The mcp-langgraph-integration whitepaper [9] established that CommandClaw must use raw httpx JSON-RPC for MCP calls to avoid the anyio conflict. This constraint was evaluated for the memory service MCP option (Option B). The conclusion: while the memory service *could* be exposed as MCP tools via commandclaw-mcp (using the existing httpx pattern), the two-hop latency (agent → gateway → memory service) and the coupling of two critical paths (tool execution and memory access) on the same gateway process are not justified when a direct REST API is available. The optional MCP surface (Section 9) is additive for agents that prefer tool-use; it is not the primary interface.

### LangGraph Deep Agents

LangChain's March 2026 Deep Agents announcement introduced a structured runtime with built-in memory and context isolation [from research]. Deep Agents uses LangGraph's BaseStore abstraction with an `/memories/` routing convention via `CompositeBackend`. The `MemoryServiceStore` shim in this whitepaper is fully compatible with this pattern — it implements the same BaseStore interface, and the namespace convention (`("agent_id", "memories")` tuples) maps cleanly to the REST API's namespace parameter.

### Scale Ceiling and Upgrade Path

The architecture as specified handles: dozens of agents, multi-year memory horizon, hundreds of thousands of memory entries in LanceDB. The scale ceiling is approximately 10M LanceDB entries before IVF_PQ parameters need retuning, and approximately 100GB vault size before git operations slow down. Both limits are far beyond what CommandClaw will reach on a single developer's machine. When the ceiling is approached, the upgrade path is: split the cold-tier vault into a separate git bare repository, or move the LanceDB hot-tier to Qdrant with a separate process. Neither change requires modifying the REST API surface or agent code.

---

## Conclusion

The CommandClaw memory service is a FastAPI HTTP microservice running on port 8284, wrapping a LanceDB vector index, backed by the git vault as the authoritative source of truth, and secured with the same phantom-token + HMAC + Cerbos RBAC pattern as commandclaw-mcp. It is exposed to LangGraph agents via a thin `MemoryServiceStore` shim that implements the standard `BaseStore` interface, making the service layer transparent to agent code.

The five-primitive framing (loop runner, perception bus, effector layer, memory layer, substrate) is validated by academic cognitive architecture research (SOAR, ACT-R) and by the convergent design of six external agent platforms. Memory (runtime-queryable, semantically indexed) and substrate (git vault, human-readable, version-controlled) are correctly identified as distinct concerns. The current CommandClaw design conflates them; this service split is the corrective architecture.

The ten design dimensions are resolved: LanceDB for storage, git-first sync with async derived indexing, async background distillation, phantom-token + HMAC + Cerbos auth, agent_id-scoped tenancy with shared namespace, REST API with BaseStore shim, circuit-breaker degradation, sub-60ms warm retrieval latency, explicit namespace promotion for cross-agent knowledge, and batch idempotent migration from flat vault files.

This architecture does not replace the git vault — it elevates it to its correct role as the substrate (cold-tier source of truth and control plane) while giving the warm tier the queryable, low-latency interface it needs to serve a multi-agent platform at scale.

---

## References

See commandclaw-memory-service-references.md for the full bibliography.
