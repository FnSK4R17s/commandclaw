# Agent Memory Architecture — Notes

<!-- Notes for the agent-memory-architecture topic. Organized by question, not source. -->
<!-- Citations are stored in whitepaper/agent-memory-architecture-references.md -->

## General Understanding

### Q1: What are the current approaches to persistent memory in AI agent systems, and how do filesystem-based memory hierarchies compare to database-backed approaches?

**Memory Taxonomy.** A December 2025 Tsinghua University survey taxonomizes agent memory by function into three categories: factual memory (storing information), experiential memory (learning from interactions), and working memory (active processing). The authors argue that traditional long/short-term taxonomies are insufficient for capturing contemporary diversity in agent memory [1].

**Leading Frameworks.** The current landscape includes several major approaches:

- **Mem0**: A pluggable memory layer that integrates into existing agent frameworks (LangChain, CrewAI) via `add()` and `search()` API calls. Uses passive extraction of memories from conversations and semantic vector search as primary retrieval. Achieved 49.0% on LongMemEval benchmark [11][17].
- **Letta (MemGPT)**: An agent runtime with a three-tiered memory model mimicking OS memory hierarchy: Core (context window, analogous to RAM), Recall (cache), and Archival (cold storage). Agents self-edit memory through deliberate tool calls rather than passive extraction [2][11].
- **Zep**: Long-term memory store for conversational AI, focused on extracting facts, summarizing conversations, and providing relevant context efficiently [2].

**Filesystem vs. Database: The Emerging Consensus.** The debate between filesystem and database approaches has converged on a hybrid answer: filesystem interface for what agents see, database storage for what persists [14][15][22].

- Filesystems are winning as an interface because models already know how to list directories, grep for patterns, read ranges, and write artifacts from their training data [14].
- Databases are winning as a substrate because once memory must be shared, audited, queried, and made reliable under concurrency, filesystem-only approaches painfully reinvent database guarantees [14].
- The "virtual filesystem" pattern is emerging where data is stored in a database but exposed to the agent as files [22].

**Letta Benchmark Result.** In benchmarks on the LoCoMo dataset, Letta's filesystem-based approach achieved 74.0% accuracy (using GPT-4o mini), outperforming Mem0's graph variant at 68.5%. The researchers concluded that "simple filesystem tools are sufficient to perform well on retrieval benchmarks" because agents effectively leverage filesystem operations from training data [3].

**Git-Native Memory Approaches.** Several projects now use Git as the versioning layer for agent memory:

- **Letta Context Repositories**: Stores agent context as local filesystem files version-controlled through Git. Supports concurrent operations across multiple subagents using separate Git worktrees, with conflict resolution through standard Git merge operations [4].
- **DiffMem**: A lightweight git-based memory backend that stores memory as Markdown files. The retrieval agent uses shell commands (grep, git log, git diff, git show) to navigate the repository like a developer would. No vector databases, embeddings, or BM25 required [5].
- **OpenViking**: ByteDance's open-source context database using a filesystem paradigm with a three-tier loading mechanism (L0/L1/L2) that reduces token consumption by retrieving only necessary context at each level [12][26].
- **Git Context Controller (GCC)**: Structures agent memory as a persistent filesystem with explicit Git-like operations: COMMIT, BRANCH, MERGE, and CONTEXT [4].

### Q2: What are the leading vector storage options for local-first AI agent memory, and how do SQLite-vec, LanceDB, ChromaDB, and Qdrant compare in performance and developer experience?

**ChromaDB**: Best-in-class developer experience. Embedded deployment (in-process, like SQLite) with zero network latency. A single VPS with 4-8 GB RAM handles millions of embeddings at under $30/month. The 2025 Rust-core rewrite delivered 4x faster writes and queries with multithreading support. Struggles with very large datasets (10M+ vectors) and lacks enterprise features [6].

**LanceDB**: Open-source embedded vector database built on the Lance columnar format. Runs in-process with zero-copy access. Uses 4MB RAM when idle and ~150MB when searching, compared to Qdrant's constant 400MB. Scales better than ChromaDB for larger-than-memory datasets. Described as "basically the SQLite of vector dbs" due to its lightweight nature [6][23][25].

**Qdrant**: Rust-based architecture with superior metadata filtering applied before vector search. Consistently faster than LanceDB especially for top-50+ searches, but uses significantly more resources (constant 400MB RAM). Docker-based deployment model. Best for complex filtering requirements. Self-hosted at $30-50/month, managed at $100-300/month [6][25].

**SQLite-vec**: SQLite extension written in C with no dependencies. Performs brute-force KNN only (no ANN indexes like HNSW). Performance at 100K vectors is sub-100ms; at 1M vectors latency exceeds 100ms for full-dimension searches. Bit-quantized vectors dramatically improve speed (11ms for 3072-dim at 1M scale). Major limitation: no ANN indexing, no metadata filtering, no partitioned storage [7].

**pgvector**: No additional infrastructure if already using PostgreSQL. Adequate performance for datasets under 2-3M vectors. Standard SQL for metadata filtering. Vector queries can impact main application performance at scale [6].

**Key Insight**: "Vector database selection represents perhaps 5-10% of RAG system quality. Chunking strategy, embedding model, retrieval pipeline, and prompt engineering matter far more" [6].

**Cost Comparison at ~1M vectors**: ChromaDB <$30/month, LanceDB <$30/month, pgvector $0-80/month, Qdrant $30-300/month, Pinecone $70-300+/month [6].

### Q3: How do hybrid retrieval strategies (BM25 + semantic search + reranking) work for agent memory retrieval, and what are the cost-performance tradeoffs?

**Core Architecture.** Hybrid search combines sparse lexical retrieval (BM25) with dense vector retrieval (embedding similarity) in parallel, then merges results using a fusion algorithm [8].

**BM25 Component.** BM25 ranks documents by term frequency in the document and inverse rarity across the corpus. Excels at exact keyword matches, error messages, identifiers, and proper nouns. Fails on paraphrases and synonyms [8].

**Semantic Search Component.** Uses high-dimensional embeddings and approximate nearest neighbor (ANN) algorithms (e.g., HNSW) to retrieve conceptually similar documents regardless of exact term overlap. Captures meaning but can miss exact matches [8].

**Fusion Methods:**
- **Reciprocal Rank Fusion (RRF)**: Assigns scores based on rank position in both keyword and vector searches. Formula: RRF(d) = sum(1/(k + r(d))). Simple, no parameter tuning required [8].
- **Convex Combination**: Weighted formula H=(1-alpha)K + alphaV where alpha balances keyword and vector scores. Requires tuning alpha per query type [8].

**Reranking Stage.** Cross-encoders re-score each query-document pair with a transformer but are expensive. Late interaction methods like ColBERT encode query and document separately and compute token-level similarity scores more efficiently [8].

**QMD Implementation.** OpenClaw's QMD (Query Markup Documents) combines BM25, vector semantic search, and LLM re-ranking in a single pipeline. Requires ~2GB disk for three GGUF models (embedding ~300MB, re-ranker ~640MB, query expansion ~1.1GB). Three search modes: `search` (BM25 only, fastest), `vsearch` (vector only), `query` (full hybrid with re-ranking, highest quality) [13].

**Cost-Performance Tradeoffs:**
- Every agent turn operates under strict latency and cost constraints. Frequent invocation of large models quickly escalates costs [28].
- Compact, structured memory records with precomputed embeddings facilitate rapid similarity search. Only a small, task-relevant subset is retrieved per interaction [28].
- Smaller models manage inexpensive steps (candidate extraction, validation), while larger models are reserved for complex reasoning [28].
- Hybrid search introduces latency overhead versus pure semantic search on large corpora [8].

### Q4: What are the emerging patterns for session lifecycle management and tiered memory (hot/warm/cold) in persistent AI agents?

**The Hot/Warm/Cold Model.** Borrowed from traditional storage tiering, this model promotes or demotes information based on relevance and access frequency [9][18]:

- **Hot Memory**: Current session context loaded at every session start. Single `memory.md` file with 200-line max. Inclusion test: "Will the next session break without this?" Uses Redis or in-memory cache (<1ms latency). Contains current priorities, recent decisions, active constraints, next actions [9][18].
- **Warm Memory**: Structured reference files in subdirectories (topic files, research docs). Agents actively pull when needed but don't load by default. Uses vector database for semantic search across recent interactions [9][18].
- **Cold Memory**: Historical archives, journal entries, superseded research. Monthly archive files. Searchable only for specific historical questions. Uses persistent storage accessed on demand [9][18].

**Consolidation Ritual.** At session end, agents triage their scratchpad: promote to hot if needed next session (update memory.md), promote to warm if enduring reference (move to topic files), archive to cold as historical record (compress to archive/YYYY-MM.md), or discard (default action for most session work). Then prune memory.md back under 200 lines [9].

**Redis Agent Memory Server Lifecycle.** Three memory creation patterns: automatic background extraction (LLM analyzes conversations), LLM-optimized batch storage (bundled with working memory updates), and direct API calls. Working memory has automatic TTL (default 1 hour). Forgetting policies include age-based, inactivity-based, combined, and budget-based (retain only top N most recently accessed) [10].

**OpenViking's L0/L1/L2 Approach.** An alternative tiering model: L0 is a one-sentence summary for quick retrieval and identification, L1 is an overview with core information for planning, L2 is full original content for deep reading. Loaded on demand to save tokens [12][26].

**Mem0 vs Letta Session Models:**
- Mem0 passively extracts memories from conversations and stores them for retrieval via API. Minimal lock-in since it acts as a pluggable layer [11].
- Letta persists AgentSession objects between invocations, allowing sessions to survive service restarts. Agent self-curates what to remember [11].

**Enterprise Scale.** At enterprise scale, memory becomes a database problem requiring vectors, graphs, relational data, and ACID transactions working together. Short-term session context must be isolated from long-term memory anchored to a profile graph [20].

### Summary

The field of AI agent memory is converging on several key patterns. First, the filesystem-vs-database debate has resolved into a hybrid architecture: filesystem interfaces for agent interaction, database substrates for persistence and retrieval at scale [14][22]. Second, git-native versioning of agent memory is a strong emerging pattern, with projects like Letta Context Repositories, DiffMem, and OpenViking all using Git for durability, auditability, and collaboration [4][5][12]. Third, for local-first vector storage, LanceDB and ChromaDB lead the embedded space with similar costs (<$30/month) but different scaling profiles; SQLite-vec is viable for small corpora but lacks ANN indexing [6][7]. Fourth, tiered memory (hot/warm/cold) is becoming standard practice, with the "consolidation ritual" at session boundaries managing promotion and demotion [9][18]. Fifth, hybrid retrieval (BM25 + semantic + reranking) consistently outperforms single-method approaches, though the full pipeline adds latency [8][13].

A notable contradiction exists: Letta's benchmarks show filesystem-only memory outperforming Mem0's specialized memory at 74.0% vs 68.5% on LoCoMo [3], while multiple sources argue that databases are essential at scale [14][20]. This is likely explained by scale: filesystem approaches work well for bounded projects with dozens to hundreds of files, but break down at hundreds of thousands of documents [9].

---

## Deeper Dive

### Subtopic A: Git-Native Memory Storage for Agent Platforms

#### Q1: How do git-based memory systems handle concurrent writes, merge conflicts, and memory compaction in multi-agent scenarios?

**Git Worktrees as the Concurrency Primitive.** The dominant pattern for handling concurrent agent memory writes is Git worktrees. Each subagent gets an isolated worktree with its own working directory, branch, and staging area. This prevents two agents from editing the same file simultaneously. When subagents complete their work, changes merge back through standard Git operations [4][29].

**Letta's Approach.** Letta's MemFS (memory filesystem) uses git-backed context repositories where memory subagents (e.g., the reflection subagent) modify the memory repo using git worktrees, allowing parallel subagents to modify memory simultaneously. Every change receives automatic version control with informative commit messages, enabling easy rollbacks and changelogs [4].

**Shared Surface Conflicts.** Worktrees share more than expected: the .git object database, the lock file system, and any tracked files modified in parallel. This creates six distinct conflict types. The fundamental advantage is that conflicts are normal Git merge conflicts at merge time rather than chaotic file overwrites during active work [29][31].

**Conflict Detection Tools.** The Clash tool performs read-only three-way merges to detect conflicts between worktree pairs before they happen. It can be wired as a pre-write hook that checks before every file edit [30].

**DiffMem's Simpler Model.** DiffMem uses atomic Git commits per session (process_and_commit_session). It does not support multi-user concurrency locks, trading concurrency support for architectural simplicity. Entities can become catch-all buckets that accumulate overload [5].

**Memory Compaction.** Letta supports "defragmentation" that reorganizes accumulated memories, targeting 15-25 focused files. This runs as a background "sleep-time" process in Git worktrees without blocking active agents [4]. Redis Agent Memory Server runs periodic compaction tasks to deduplicate memories and maintain search index performance [10].

#### Q2: What is the optimal Markdown-based memory file structure for a git-native agent vault?

**The Progressive Disclosure Pattern.** Memory should be organized as a hierarchy where agents see directory structure in their system prompt and progressively load files as needed. The ideal structure keeps root-level context small and points to deeper files [9][12].

**OpenViking's L0/L1/L2 Structure.** OpenViking implements a tiered directory approach using the `viking://` URI scheme [12][39]:
```
viking://resources/project/
  .abstract    # L0: one-sentence summary (~100 tokens)
  .overview    # L1: core info for planning (~2k tokens)
  docs/
    .abstract
    .overview
    api/
      auth.md  # L2: full content for deep reading
```
Initial retrieval scans L0 abstracts for broad relevance. High-scoring directories trigger L1 loading. L2 content loads only on explicit agent request. Child L0 abstracts aggregate into parent L1 overviews, creating hierarchical navigation [12][39].

**The Hot Memory Pattern.** A single `memory.md` file (200-line max) loaded at every session start, containing only time-critical information. Topic files and research documents in subdirectories serve as warm reference. Monthly archives serve as cold storage [9].

**memsearch's Approach.** Markdown files are the source of truth; the vector store is a derived, rebuildable index. Files are chunked by heading structure and paragraph boundaries, then embedded. SHA-256 content hashing prevents re-embedding unchanged sections [32][33].

**Anti-Patterns.** A single monolithic MEMORY.md file that grows unbounded is the most common failure mode. A 15,000-token memory file injected into every API call costs approximately $555/month at 100 daily requests. Over three months, files grow to contain contradictory preferences, stale projects, and inconsistent formats [34].

#### Q3: What are the practical integration patterns for combining git-native storage with vector search indexing?

**The "Markdown as Source of Truth" Pattern.** memsearch demonstrates the canonical approach: Markdown files in a git-tracked directory are the authoritative data store. A file watcher (configurable debounce, default 1500ms) monitors changes and auto-indexes new/modified files. The vector database (Milvus) is a derived index, rebuildable anytime from the Markdown source [32].

**memsearch Pipeline Details.** Ingest: chunk by heading/paragraph boundaries, deduplicate via SHA-256, embed only new chunks, upsert to Milvus. Search: hybrid retrieval combining dense vector search with BM25 full-text matching, fused via Reciprocal Rank Fusion (RRF). Supports multiple embedding providers: ONNX (BGE-M3 int8, local CPU), sentence-transformers (local), OpenAI/Gemini/Voyage (cloud), Ollama (self-hosted) [32].

**QMD Integration.** OpenClaw's QMD auto-indexes MEMORY.md and memory/**/*.md files. Creates an environment at ~/.openclaw/agents/<agentId>/qmd/. Text indexing runs via `qmd update` (fast). Vector embeddings run via `qmd embed` (slower initially). Background re-indexing every 5 minutes. Three search modes: BM25-only (fastest), vector-only (semantic), or full hybrid with LLM re-ranking (highest quality) [13].

**Sync Challenges.** The key challenge is maintaining consistency between the git-tracked Markdown and the vector index. File watchers handle this for local development, but distributed scenarios (multiple machines, CI/CD) require explicit rebuild steps. The advantage of a derived index is that it can always be rebuilt from source, making corruption recoverable [32][33].

### Subtopic B: Embedding Strategy and Local Model Selection

#### Q1: What are the best local/self-hosted embedding models for agent memory in 2026?

**Top Models by MTEB Score** [16]:

| Model | MTEB | Cost/1M Tokens | Dims | Self-Host |
|-------|------|----------------|------|-----------|
| Qwen3-Embedding-8B | 70.58 | Free | 7,168 | Yes |
| NV-Embed-v2 | 69.32 | Free | 4,096 | Yes (NC) |
| BGE-M3 | 63.0 | Free | 1,024 | Yes |
| Nomic embed-text-v1.5 | ~62 | Free | 768 | Yes |
| all-MiniLM-L6-v2 | 56.3 | Free | 384 | Yes |

**Cloud Comparison**: OpenAI text-embedding-3-large scores 64.6 MTEB at $0.13/1M tokens; Voyage-3-large scores ~67+ at $0.06/1M tokens [16].

**Practical Recommendations for Local:**
- **Best quality**: Qwen3-Embedding-8B (top MTEB, Apache 2.0) but requires GPU [16].
- **Best multi-purpose**: BGE-M3 supports dense, sparse, and multi-vector retrieval from a single model under MIT license [16][24].
- **Best lightweight**: Nomic embed-text-v1.5 with fully open weights, code, and training data under Apache 2.0. Runs on Ollama with 768 dims and 8K context [16][24].
- **Prototyping/CPU**: all-MiniLM-L6-v2 enables sub-10ms CPU inference for architecture validation [16].

**GGUF for Local Embedding.** Qwen3-Embedding series offers 0.6B, 4B, and 8B variants in GGUF format. GGUF retains ~92% quality after quantization. The 0.6B model is suitable for CPU-only deployments [42].

**QMD's Local Stack.** QMD uses three GGUF models totaling ~2GB: embedding model (~300MB), re-ranker (~640MB), query expansion (~1.1GB). Runs entirely local with no API keys [13].

#### Q2: How should embedding dimensionality, quantization, and Matryoshka truncation be configured for agent memory?

**Matryoshka Representation Learning.** MRL trains models to store important information in earlier dimensions. During training, a loss function evaluates embedding quality at multiple dimensionalities (e.g., 768, 512, 256, 128, 64) simultaneously. This incentivizes "frontloading" important information [36].

**Performance Retention.** At 8.3% of full embedding size (64/768 dimensions), Matryoshka models preserve 98.37% of performance vs. 96.46% for standard models. OpenAI's text-embedding-3-large truncated to 256 dimensions still outperforms the older full-size 1,536-dimension ada-002 [36].

**Practical Dimension Choices.** Common: 64 (maximum savings, ~1.6% loss), 128 (good balance), 256 (near-full performance). Important: embeddings must be re-normalized after truncation [36].

**Shortlisting and Reranking.** Use truncated embeddings (e.g., 64-128 dims) for fast initial filtering, then rerank with full-size embeddings for accuracy. This two-stage approach is well-suited to agent memory where you want fast candidate retrieval followed by precise selection [36].

**Binary Quantization.** Converts 32-bit embeddings to 1-bit, achieving up to 40x speed improvement. However, for embeddings under 1024 dimensions, accuracy degradation may be too severe. Rescoring (using original vectors for top candidates) mitigates precision loss. Asymmetric quantization (binary stored vectors + scalar quantized queries) maintains storage savings while improving precision [37][38].

**For Agent Memory (Small Corpus, High Precision).** With corpora under 100K chunks, the bottleneck is not search speed but embedding quality and retrieval precision. Recommended: use full-dimension embeddings (768 or 1024) with a high-quality local model like Nomic or BGE-M3. Apply Matryoshka truncation only if storage or latency constraints demand it. Avoid binary quantization for small corpora since the precision trade-off is not worth the storage savings at this scale [36][37].

### Subtopic C: CommandClaw-Specific Design

#### Q1: What concrete architecture best combines tiered memory with hybrid retrieval for a git-vault-as-control-plane agent?

**The Git Vault Pattern.** The git repository is the single source of truth for all agent state. Memory files (Markdown) live in the vault and are version-controlled. The vector index is a derived artifact, rebuildable from the vault contents [4][5][32].

**Recommended Tiered Architecture:**

1. **Hot tier (system prompt)**: A curated `MEMORY.md` (under 200 lines) loaded into every agent invocation. Contains current project state, active constraints, recent decisions, and next actions. Updated at session boundaries [9].

2. **Warm tier (indexed reference)**: Topic-organized Markdown files in a `memory/` directory. Indexed by a local vector search engine (LanceDB or memsearch-style pipeline). Agent retrieves via hybrid search when hot memory is insufficient. Files are human-editable and git-versioned [9][13][32].

3. **Cold tier (archived history)**: Monthly archive files in `archive/YYYY-MM.md` format. Session transcripts and superseded decisions. Not indexed by default; searchable via git log/grep when investigating historical questions [9].

**Retrieval Pipeline.** For the warm tier: ingest Markdown chunks, embed with a local model (Nomic embed-text-v1.5 or BGE-M3), store in LanceDB. At query time, run BM25 + vector search in parallel, fuse via RRF, optionally rerank with a small local model. QMD provides a ready-made implementation of this pipeline [13][32].

**Session Lifecycle.** At session start: load hot memory into system prompt, optionally pre-fetch warm memories relevant to the task. During session: agent writes to scratchpad. At session end: consolidation ritual - promote important findings to hot/warm, archive session to cold, prune hot memory back under limits, commit all changes to git [9][10].

#### Q2: What are the failure modes and operational pitfalls at personal/team agent scale?

**Token Bloat.** The most predictable failure: MEMORY.md grows linearly but cost grows multiplicatively since every API call includes the full file. At 15,000 tokens and 100 daily requests, this costs ~$555/month. At 6 months, files contain contradictory preferences and stale projects [34].

**Retrieval Degradation.** LLMs perform best when relevant information is at the beginning or end of context but significantly worse when buried in the middle (the "attention dead zone"). Agents work well on 50-file projects but degrade on 500-file projects not because of token limits, but because relevant information lands in this dead zone [34][35].

**Concurrent Write Corruption.** Without proper isolation (git worktrees), concurrent filesystem writes silently corrupt data. This is especially problematic for multi-agent setups where a coordinator and worker agents share memory [29][34].

**Index Drift.** If the vector index is not kept in sync with the Markdown source, agents retrieve stale or deleted content. File watchers mitigate this locally, but distributed deployments need explicit rebuild mechanisms [32].

**Semantic Search False Positives.** At small scale, semantic search can surface plausible but wrong memories (e.g., a discussion about "Python memory management" surfacing when asking about "agent memory architecture"). This is more pronounced with small embedding models and low-dimensional vectors [34].

**Mitigation Strategies:**
- Enforce memory.md size limits (200 lines) with automated pruning [9]
- Use tiered architecture to keep hot context small and relevant [9][18]
- Run vector index sync as a background process with file watching [32]
- Use git worktrees for concurrent access isolation [4][29]
- Prefer hybrid retrieval (BM25 + semantic) to catch both exact and conceptual matches [8][13]
- Schedule periodic compaction/defragmentation to merge duplicates and remove stale entries [4][10]

### Summary

The deeper dive reveals three critical design axes for CommandClaw's memory system.

First, **git-native concurrency** is a solved problem at the agent-team scale. Git worktrees provide per-agent isolation, and tools like Clash detect conflicts before they happen. The key insight from Letta's Context Repositories is that memory subagents should run in worktrees and merge back, using standard Git operations for conflict resolution [4][29][30].

Second, **embedding strategy** should prioritize quality over efficiency for small-corpus agent memory. Local models like BGE-M3 (1024d, MIT license) or Nomic embed-text-v1.5 (768d, Apache 2.0) provide strong retrieval quality with zero API cost. Matryoshka truncation offers a principled way to reduce dimensions if needed (64d retains 98.37% of quality), but at agent-memory scale the storage savings are unlikely to matter [16][36]. GGUF-quantized models enable CPU-only inference with ~92% quality retention [42].

Third, **the filesystem-at-scale problem** is real but manageable. The critical failure is not filesystem capacity but context window pollution: unbounded memory files degrade retrieval quality through the attention dead zone effect. The mitigation is strict tiered architecture with automated size enforcement, not a wholesale move to databases. For CommandClaw's target scale (personal/team, thousands of sessions), a git-tracked Markdown vault with a derived LanceDB or memsearch-style vector index provides the best balance of inspectability, versioning, and retrieval quality [9][32][34]. The architecture should be designed so that the vector index is always rebuildable from the Markdown source, ensuring the git vault remains the single source of truth [32].
