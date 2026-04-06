# commandclaw-memory-service — Notes

<!-- Notes for the commandclaw-memory-service topic. Organized by question, not source. -->
<!-- Citations are stored in whitepaper/commandclaw-memory-service-references.md -->

## General Understanding

### Q1: How do leading agent platforms decompose their architecture — is the PERCEIVE→THINK→ACT→REMEMBER loop model correct?

**Finding 1: No universal convergence on a canonical loop model.**

A survey of leading agent platforms reveals that architectural decompositions vary substantially. LangGraph uses a graph-of-nodes model (StateGraph with conditional edges) rather than a strict sequential loop — the "loop" is implicit in cycles in the graph, not an explicit runtime primitive [1]. AutoGen uses a ConversableAgent abstraction where the loop is encoded in the message-passing protocol between agents rather than in a named cognitive cycle [2]. Pydantic AI uses a dependency-injection model where the "loop" is a run() call that resolves tool calls until the model returns a final response [3].

AWS documentation describes only three primitives for agent operation: **perceive**, **reason**, and **act** — memory is treated as implicit state rather than an explicit fourth primitive [4]. The Langfuse framework comparison survey (covering LangChain, AutoGen, smolagents, Pydantic AI, CrewAI) found that while frameworks agree on the necessity of perception, action, and some form of state, the memory layer is the most inconsistently handled primitive across platforms.

**Finding 2: Academic framing provides stronger support for a four-to-five primitive model.**

Academic work (arXiv 2601.12560) frames agent cognition as a POMDP tuple with four irreducible functions: Perception (Φ), Memory Update (μ), Cognitive Planning (Ψ), and Action Policy (π) [5]. This maps cleanly onto a five-primitive model where the "substrate" (git vault) is added as the fifth primitive — not a cognitive function but a persistence and auditability layer external to the cognitive loop.

**Finding 3: The five-primitive framing is defensible as a CommandClaw-specific architectural primitive model.**

The five-primitive framing proposed for CommandClaw — (1) loop runner, (2) perception bus, (3) effector layer, (4) memory layer, (5) substrate — does not contradict any existing platform's architecture; rather, it makes explicit what other platforms leave implicit. The critical insight: **vault and memory are two distinct concerns**. The substrate (git vault) is the audit-grade source of truth with commit history and human-readable Markdown; the memory layer is the runtime-queryable, semantically indexed store optimized for agent retrieval. Conflating these two (as the current CommandClaw design does by loading vault files wholesale into the system prompt) creates a correctness/auditability conflation that degrades both concerns.

---

### Q2: Dedicated agent memory services — service vs embedded, tenancy model, API surface

**Finding 1: The memory service landscape has converged on two main deployment patterns.**

Five production-grade agent memory systems have been surveyed [6][7][8]:

- **Letta/MemGPT**: Full agent runtime, not a standalone memory service. Implements a three-tier model: core memory (in-context, fast), recall memory (vector search over conversation history), archival memory (long-term storage). Deployed as a separate Letta server process with a REST API. Tenancy: per-agent memory blocks with agent_id scoping. Distillation: triggered by context window pressure using the same LLM.
- **Mem0**: Pluggable memory service. Can run embedded (Python library) or as a hosted service. Tenancy: user_id + agent_id + run_id triple. Storage: vector (Qdrant/Chroma/pgvector) + graph (Neo4j optional). Distillation: async background worker, LLM-based fact extraction. API: add/search/get/delete.
- **Cognee**: Embedded library with SQLite + LanceDB + Kuzu graph database. No separate service process. Distillation: synchronous on write via a cognify() pipeline. API: cognify(data), search(query). Tenancy: dataset_id scoping.
- **Zep/Graphiti**: Temporal knowledge graph. Zep is a standalone service (Neo4j or embedded graph), Graphiti is its open-source core. Distillation: async background, extracts entities/facts/temporal edges. API: memory/add, memory/search, graph/node/search. Tenancy: session_id + user_id.
- **OpenMemory/Hindsight**: MCP memory servers. OpenMemory uses Qdrant + PostgreSQL backend. Hindsight runs as a local process and exposes retain/recall/reflect MCP tools. Both are separate processes with MCP protocol surface.

**Finding 2: MCP-native memory servers are an emerging pattern but impose the anyio conflict on CommandClaw.**

Hindsight and OpenMemory expose memory via the MCP protocol, meaning agents call retain/recall as tool calls in the natural tool-use flow. This is architecturally elegant for CommandClaw because it fits the existing MCP gateway pattern. However, per the MCP-LangGraph integration whitepaper, CommandClaw must use raw httpx JSON-RPC to avoid the anyio conflict — this constraint applies equally to a memory MCP server [9]. The phantom-token + HMAC auth pattern from commandclaw-mcp would transfer directly.

**Finding 3: Embedded vs service is a false dichotomy at single-machine scale.**

At single-machine, single-developer scale (CommandClaw's target), the distinction between "embedded" and "separate process" is primarily about process isolation and upgrade independence, not about network latency (which is loopback). The real decision axis is: **does the memory layer need to be independently deployable, upgradeable, and fault-isolated from the agent runtime?** For CommandClaw, the answer is yes — the memory service will be queried by multiple agents (BEARY, the main assistant, future agents), benefit from independent restart without killing running agent sessions, and serve as the single source of truth for runtime memory across agents.

---

### Q3: Storage backend trade-offs at multi-agent, multi-year scale

**Finding 1: LanceDB remains the leading choice for single-machine embedded vector storage.**

LanceDB uses a columnar Lance file format that stores data as Arrow files on disk. It supports IVF_PQ indexing (40–60ms query at 1M vectors), requires zero infrastructure, and has a Python API that mirrors Pandas. At multi-year, dozens-of-agents scale, a single LanceDB instance on disk handles well over 10M vectors before requiring sharding [10]. The prior agent-memory-architecture whitepaper selected LanceDB for the same reasons — this finding reinforces that choice.

**Finding 2: Qdrant offers better performance isolation but adds operational overhead.**

Qdrant runs as a Rust process with HNSW indexing (20–30ms at 1M vectors, 400MB RAM constant overhead). It provides a gRPC + REST API, supports scalar quantization to halve memory use, and has production-grade filtering. The cost is: a separate process to manage, a separate health check, and Docker compose complexity. At CommandClaw's current scale (dozens of agents, not hundreds), Qdrant's performance advantages do not justify the operational overhead over LanceDB [10].

**Finding 3: pgvector eliminates a separate store if Postgres is already present but has query latency limitations.**

pgvector adds vector similarity search to PostgreSQL. The agent-logic-refactor whitepaper established that CommandClaw uses PostgresSaver as its LangGraph checkpointer — meaning Postgres is already in the stack [11]. pgvector queries run 80–150ms at 1M vectors (slower than dedicated vector stores) and lack native IVF_PQ support. It is appropriate for warm/cold retrieval but unsuitable for hot-path semantic recall where sub-100ms is required.

**Finding 4: ChromaDB is best for development but has scalability ceiling.**

ChromaDB has excellent DX (simple Python API, automatic persistence) but is single-threaded in its embedded mode and hits performance walls above 10M vectors. At multi-year memory horizon with dozens of agents writing continuously, ChromaDB is not recommended as the primary store. It remains useful for local development and testing [10].

**Synthesis: Hot/warm/cold tiering confirmed. LanceDB for hot, pgvector for warm, flat vault for cold.**

The storage architecture from the prior whitepaper (hot: in-context MEMORY.md ≤200 lines; warm: LanceDB vector index; cold: git vault Markdown files) is confirmed and refined:
- Hot (in-context): MEMORY.md loaded at agent start, ≤200 line limit
- Warm (runtime retrieval): LanceDB IVF_PQ index, sub-60ms semantic recall
- Cold (archival + human audit): git vault flat Markdown files, never queried by vector search directly

---

### Q4: Sync models for Git vault + memory service consistency

**Finding 1: Post-commit hooks are the canonical pattern for triggering memory indexing from git events.**

The "agentmemory" project and similar systems use `post-commit` git hooks to trigger background re-indexing of changed files. The hook writes to a queue (e.g., a SQLite table or simple file) that a background daemon processes asynchronously [12]. This decouples the commit latency (fast, synchronous) from the indexing latency (slow, async). The Beads project uses a similar pattern: JSONL memory logs + SQLite cache + background refresh daemon, with the git repo as the append-only source of truth [12].

**Finding 2: Dual-write (write to git + write to vector index in the same transaction) is simpler but creates consistency risk.**

Dual-write is the approach used by Cognee: on every cognify() call, it writes to SQLite AND to LanceDB atomically (within a Python transaction). The risk: if the vector write succeeds but the git commit fails (or vice versa), the stores diverge. For CommandClaw, where the git vault is the authoritative source of truth, the correct pattern is: **git commit is primary, vector index is derived**. This means: (1) commit to git vault first; (2) trigger async re-index of changed files; (3) serve stale-but-consistent vector results until re-index completes.

**Finding 3: File watchers are unreliable at agent scale; prefer event-driven hooks.**

File watchers (inotify, watchdog) work well for single-process scenarios but become unreliable when multiple agents write to the vault concurrently (missed events, race conditions on rapid writes). A post-commit hook or a post-push webhook is more reliable because git serializes commits. The commandclaw-vault repo already uses git as its serialization primitive — the sync model should extend this rather than adding a parallel watcher [13].

**Finding 4: Letta's "context repositories" use git worktrees for concurrent agent memory isolation.**

Letta's recent context repositories feature assigns each agent a git worktree of a shared repository, allowing concurrent reads and writes without locking. Merges are handled via git. This pattern is directly applicable to CommandClaw: each agent session gets a worktree of the vault repo; post-merge hooks trigger re-indexing into the shared LanceDB instance [14].

---

### Summary

1. The five-primitive framing (loop runner, perception bus, effector layer, memory layer, substrate) is academically defensible and not contradicted by any surveyed platform. It is the correct model for CommandClaw.
2. Memory and substrate are two distinct concerns. The current design conflating them (wholesale vault load into system prompt) degrades both retrieval quality and auditability.
3. A separate memory service process is warranted — it should expose an HTTP/REST API (not MCP, to avoid anyio complications) optionally fronted by an MCP adapter at the gateway level.
4. LanceDB remains the recommended storage backend for the warm (vector) tier.
5. The sync model should be git-first (derived index), with post-commit hooks triggering async re-indexing.

---

## Deeper Dive

### Subtopic A: Five-Primitive Framing Validation

#### Q1: Do agent platforms outside the LangChain ecosystem use a different decomposition that would break or refine the five-primitive model?

**Finding 1: AutoGen (Microsoft) uses an actor model, not a loop model.**

AutoGen v0.4+ (Magentic-One, AutoGen AgentChat) decomposes agents as actors in a message-passing system. There is no explicit PERCEIVE→THINK→ACT→REMEMBER loop — instead, agents respond to messages and emit messages. The "memory" in AutoGen is carried in the message history (a list of messages), not in a separate store [2]. This does not break the five-primitive model; it shows that the loop runner (primitive 1) can be an actor runtime rather than a graph runtime.

**Finding 2: smolagents (HuggingFace) uses a CodeAgent with a minimal loop.**

smolagents CodeAgent executes a simple while loop: LLM generates Python code → code is executed → result is fed back as observation → repeat until done [15]. There is no explicit memory primitive; the agent's "memory" is the list of prior (code, observation) pairs accumulated in context. The five-primitive model maps cleanly: loop runner = the while loop, perception bus = the observation feed, effector = the code executor, memory = the accumulation of (code, observation) pairs, substrate = absent (no persistence by default). The CommandClaw five-primitive model *adds* what smolagents leaves out.

**Finding 3: Pydantic AI uses a structured dependency injection model.**

Pydantic AI's "deps" (dependencies) pattern allows agents to receive typed context objects at runtime [3]. There is no named memory primitive — memory would be injected as a dep. This is compatible with the five-primitive model: the memory layer is the dep injection mechanism. The five-primitive model is a superset.

**Finding 4: Mastra (TypeScript) uses a workflow + agent composition model.**

Mastra distinguishes between workflows (deterministic step sequences) and agents (LLM-driven) [16]. Memory in Mastra is an explicit primitive: `agent.memory` is a MemoryProcessor that wraps a storage backend. This is the closest external platform to the five-primitive model's explicit memory layer — it validates the design.

**Verdict: The five-primitive model is a refinement, not a contradiction, of all surveyed platforms. It makes explicit what most platforms leave implicit.**

---

#### Q2: How do academic frameworks for cognitive architectures (SOAR, ACT-R) map to the five-primitive model?

**Finding 1: SOAR's production memory maps to the substrate; working memory maps to the hot tier.**

SOAR (State, Operator, And Result) uses production memory (long-term rules), semantic memory (long-term declarative facts), episodic memory (experience replay), and working memory (current problem state) [17]. The mapping to CommandClaw five primitives:
- Working memory → hot tier (MEMORY.md in context)
- Semantic + episodic memory → warm tier (LanceDB vector index)
- Production memory → substrate (git vault rules/policies)
- The "loop" = SOAR's decision cycle (Propose → Evaluate → Apply)

**Finding 2: ACT-R's declarative vs procedural distinction maps onto substrate vs memory layer.**

ACT-R distinguishes procedural memory (how to do things, compiled rules) from declarative memory (facts, episodic chunks) [17]. In CommandClaw: procedural = agent skills/instructions in the vault (substrate), declarative = runtime memories indexed in LanceDB (memory layer). ACT-R's "retrieval" module (spreading activation to find relevant chunks) maps directly to the hybrid BM25+vector retrieval in the memory service.

**Finding 3: The "substrate" primitive has no ACT-R/SOAR equivalent — it is a distributed systems addition.**

Neither SOAR nor ACT-R has a "substrate" primitive in the sense of an external audit-grade persistence layer with human-readable format and version history. This is a correct addition for a production multi-agent system: the substrate is the control plane, not a cognitive function. The five-primitive model correctly separates cognitive functions (1–4) from the control-plane function (5).

---

#### Q3: Is "substrate" a recognized architectural primitive, or does it conflate two concepts?

**Finding 1: The git vault is doing two distinct jobs that could be separated.**

On inspection, the CommandClaw vault (commandclaw-vault) serves two roles: (a) configuration/policy source of truth (agent skills, user profile, system prompts — read by agents at startup) and (b) memory archive (cold-tier memory files — written by agents as they accumulate experience). These are logically distinct: (a) is a configuration management function, (b) is a cold-tier memory function. The five-primitive model's "substrate" conflates these, but at CommandClaw's current scale this is acceptable — separating them would add operational complexity without benefit.

**Finding 2: "Substrate" is used in distributed systems literature to mean the underlying execution and persistence infrastructure.**

In the Temporal.io and Inngest agent runtime context, "substrate" refers to the durable execution engine that persists workflow state across failures [18]. This maps well to the git vault's role: it is the durable, human-readable substrate that survives process crashes, restores agent state, and provides the audit trail. The term is justified.

**Verdict: "Substrate" is an appropriate and recognized term. The two roles it plays (configuration + cold memory) are a manageable conflation at current scale, with a clear upgrade path to split them when needed.**

---

### Subtopic B: Memory Service Architecture Deep Dive

#### Q1: How does Letta (MemGPT) architect its memory service internally?

**Finding 1: Letta runs as a standalone FastAPI server with PostgreSQL + LanceDB backend.**

Letta's server (letta-server Docker image) runs a FastAPI application on port 8283. It uses PostgreSQL for agent state, message history, and metadata; LanceDB (or optionally Qdrant) for vector embeddings over archival memory [6]. Each agent has its own memory blocks (core_memory dict stored in Postgres, archival_memory in the vector store). The REST API surface: `/v1/agents/{agent_id}/memory`, `/v1/agents/{agent_id}/archival-memory` (search/insert/delete), `/v1/agents/{agent_id}/messages`.

**Finding 2: Letta's tenancy model is agent_id-scoped with optional org_id.**

Every memory operation is scoped to an agent_id. There is no native cross-agent memory sharing in the open-source version — cross-agent memory would require reading from a shared "organization" agent or using the archival memory of a designated "memory agent" that other agents query [6].

**Finding 3: Letta's distillation is context-pressure-triggered, using the active LLM.**

When an agent's context window fills, Letta invokes the agent's own LLM to summarize and compress the in-context memory, then writes the summary to archival memory. This is synchronous and blocks the agent. The distillation prompt is part of the system prompt template.

**Implication for CommandClaw: Letta's architecture validates the pattern but is over-engineered for CommandClaw's needs.** CommandClaw does not need a full agent runtime embedded in the memory service — it needs storage, retrieval, and distillation as separate concerns.

---

#### Q2: How do Zep, Cognee, Graphiti, and Mem0 differ in their distillation approach?

**Finding 1: Zep/Graphiti uses async background distillation with a dedicated extraction LLM.**

Zep's memory pipeline: on each `memory/add` call, facts and entities are extracted asynchronously by a background worker using an LLM configured separately from the agent LLM [8]. Entity resolution (deduplication), edge creation in the knowledge graph, and summary generation all happen in the background. The agent continues immediately — distillation is non-blocking.

**Finding 2: Mem0 uses async background distillation with a configurable extraction model.**

Mem0's pipeline: `memory.add(messages, user_id=..., agent_id=...)` returns immediately; a background worker extracts facts using an LLM (configurable — can use a smaller/cheaper model than the main agent LLM), deduplicates against existing memories, and writes to the vector store [7]. Distillation frequency: per-session-end by default, configurable.

**Finding 3: Cognee uses synchronous distillation — cognify() blocks until complete.**

Cognee's `cognify(data)` call runs the full graph construction pipeline synchronously: chunk → embed → extract entities → build knowledge graph → persist to LanceDB + Kuzu [19]. This is appropriate for offline batch ingestion but unsuitable for real-time agent memory writes.

**Synthesis for CommandClaw: async background distillation is the right model.** The memory service should accept write requests immediately (with a 202 Accepted response) and distill asynchronously using a small, fast model (BGE-small-en-v1.5 for embeddings, a lightweight LLM or regex-based extractor for fact extraction). This mirrors Mem0's and Zep's pattern.

---

#### Q3: What auth model is appropriate for an internal memory service?

**Finding 1: mTLS is overkill at single-machine scale; API key with HMAC-signed requests is appropriate.**

Service mesh mTLS (Istio, Linkerd) adds certificate management overhead that is unjustified on a single machine [20]. The phantom-token + HMAC pattern from commandclaw-mcp is directly applicable: the memory service issues an internal service token to each caller (agent or gateway), and each request includes an HMAC signature over method+path+timestamp+nonce+body_hash. This provides request integrity verification without TLS overhead on loopback.

**Finding 2: The auth model should be configurable to allow no-auth in development.**

In development, the memory service should support a `MEMORY_AUTH_DISABLED=true` mode that bypasses all auth checks. This is consistent with the commandclaw-mcp gateway pattern.

**Finding 3: Cerbos RBAC should govern memory read/write/delete permissions at agent level.**

Since different agents have different memory access scopes (BEARY should not be able to delete main assistant memories, for example), Cerbos RBAC policy should be applied at the memory service level, using the existing Cerbos instance. This is consistent with the existing commandclaw-mcp RBAC pattern.

---

### Subtopic C: Graceful Degradation and Failure Modes

#### Q1: What is the established pattern for graceful degradation when a memory service is unavailable?

**Finding 1: Circuit breaker + hot-tier fallback is the standard pattern.**

When the memory service is unavailable (crash, restart, network timeout), the agent should: (1) detect the failure via health check or connection error; (2) trip a circuit breaker (open state); (3) fall back to the hot tier only (MEMORY.md in context) for the duration of the session [21]. This mirrors the MCP gateway degradation pattern already built in commandclaw-mcp.

**Finding 2: Memory writes should be queued, not dropped, during outages.**

When the memory service is down, new memories generated by the agent during the session should be written to a local buffer (a simple append-only file in the vault) and replayed to the memory service on reconnection. This prevents memory loss during short outages.

**Finding 3: The vault is the ultimate fallback for cold retrieval.**

If the memory service is down and the agent needs to retrieve memories beyond the hot tier, it can fall back to keyword search over the vault's flat Markdown files (using grep or a simple inverted index). This is slower (seconds, not milliseconds) but available. The agent should log a warning and degrade gracefully, not fail hard.

---

#### Q2: What are the migration patterns for bootstrapping a new vector memory service from existing flat Markdown files?

**Finding 1: Batch embedding is the standard bootstrap migration pattern.**

The migration pipeline: (1) enumerate all Markdown files in the vault; (2) chunk each file (512-token chunks with 50-token overlap); (3) embed each chunk using BGE-small-en-v1.5 (already cached); (4) write to LanceDB with metadata (source_file, chunk_index, agent_id, timestamp, content_type) [22]. This is a one-time batch job, estimated at 2–5 minutes for a typical vault (hundreds of files, thousands of chunks).

**Finding 2: Incremental migration is preferable to big-bang.**

Rather than migrating all files at once, the migration should proceed in priority order: (1) MEMORY.md files first (hot-tier source); (2) memory/*.md files (warm-tier source); (3) archive/*.md files (cold-tier source). This ensures the memory service is useful immediately after partial migration.

**Finding 3: Idempotent writes via content hash prevent duplicate embeddings.**

Each chunk should be written with a content_hash field. Before writing, the migration pipeline checks if a chunk with the same content_hash already exists in LanceDB. If so, it skips the write. This makes the migration pipeline safe to re-run after interruption.

---

### Deeper Dive Summary

1. The five-primitive model is validated against academic (SOAR, ACT-R) and platform (AutoGen, smolagents, Pydantic AI, Mastra) architectures. No platform breaks the model; several (Mastra, Letta) implicitly implement it.
2. Letta validates the separate-service pattern but is over-engineered. Mem0 and Zep validate the async distillation pattern. Cognee validates LanceDB as storage but uses synchronous distillation (not recommended).
3. Auth: phantom-token + HMAC + Cerbos RBAC, consistent with commandclaw-mcp. mTLS is overkill.
4. Graceful degradation: circuit breaker → hot-tier fallback → local write buffer → vault keyword fallback.
5. Migration: batch embed with BGE-small-en-v1.5, incremental by tier, idempotent via content hash.
