# Agent Memory Architecture for Persistent AI Agents

**Author:** Background Research Agent (BEARY)
**Date:** 2026-03-29

---

## Abstract

This whitepaper examines memory architecture for persistent AI agents, with a focus on designing the memory system for CommandClaw -- a Python/LangChain agent platform where the git vault serves as the control plane. We survey the current landscape of agent memory frameworks (Mem0, Letta, Zep, OpenViking, DiffMem), compare storage substrates (filesystem vs. vector database vs. hybrid), evaluate vector storage options (LanceDB, ChromaDB, SQLite-vec, Qdrant) for local-first deployments, analyze hybrid retrieval strategies (BM25 + semantic search + reranking), and assess tiered memory patterns (hot/warm/cold) with session lifecycle management. The central finding is that a git-tracked Markdown vault with a derived vector index provides the best balance of inspectability, versioning, and retrieval quality for personal/team-scale agent platforms. We recommend a three-tier architecture with strict size-enforced hot memory, hybrid-indexed warm reference, and git-archived cold storage, using a local embedding model (BGE-M3 or Nomic embed-text-v1.5) with LanceDB as the derived vector store.

## Introduction

Memory is the distinguishing capability that separates a stateless language model from a persistent agent. Without memory, every agent invocation starts from zero -- no awareness of past decisions, no accumulation of knowledge, no continuity of context. As AI agents move from single-turn tools to long-running collaborators, the memory system becomes the critical substrate for agent identity and effectiveness.

The challenge is not merely storing information but designing a system that balances multiple competing requirements: fast retrieval for real-time interaction, human inspectability for trust and debugging, version control for auditability, and graceful scaling from tens to tens of thousands of memory entries. For CommandClaw specifically, the additional constraint is that the git vault must be the control plane -- memory must be inspectable, editable, and versioned as plain files in a git repository.

This whitepaper addresses four core questions: (1) What storage format and architecture best serves a git-native agent platform? (2) Which vector database and embedding model should be used for local-first retrieval? (3) How should retrieval combine keyword and semantic search? (4) How should sessions be managed and memory tiered across hot, warm, and cold storage?

## Background

### The Agent Memory Taxonomy

A December 2025 survey from Tsinghua University [1] provides the most comprehensive taxonomy of agent memory to date. It classifies memory by function into three categories: factual memory (storing information), experiential memory (learning from interactions), and working memory (active processing). The authors argue that the traditional long-term/short-term dichotomy is insufficient for modern agent systems, which require more nuanced representations of how memory is formed, evolved, and retrieved.

### The Filesystem vs. Database Debate

The 2025-2026 period saw intense debate over whether agent memory should be stored as files or in databases. This debate has largely converged on a hybrid answer: filesystem interfaces for what agents see, database substrates for what persists [14][15][22]. Models already know how to list directories, grep for patterns, and read files from their training data, making filesystem interfaces a natural fit [14]. However, once memory must be shared across agents, queried at scale, or made reliable under concurrency, filesystem-only approaches painfully reinvent database guarantees [14].

The "virtual filesystem" pattern has emerged as the practical synthesis: data stored in a database but exposed to the agent as files [22]. For CommandClaw, this maps directly to the design constraint: Markdown files in a git vault (the interface) backed by a derived vector index (the retrieval substrate).

### Leading Memory Frameworks

The current landscape includes several prominent approaches, each representing a different architectural philosophy:

**Mem0** functions as a pluggable memory layer that integrates into existing agent frameworks via simple `add()` and `search()` API calls. It uses passive extraction of memories from conversations and semantic vector search as primary retrieval. It achieved 49.0% on the LongMemEval benchmark [11][17].

**Letta (MemGPT)** operates as a complete agent runtime with a three-tiered memory model mimicking OS memory hierarchy: Core (context window), Recall (cache), and Archival (cold storage). Agents self-edit memory through deliberate tool calls rather than passive extraction [2][11].

**OpenViking** is ByteDance's open-source context database that organizes memory through a filesystem paradigm with a three-tier loading mechanism (L0/L1/L2) that progressively loads context on demand to minimize token consumption [12][26].

A notable benchmark result from Letta challenges the assumption that specialized memory tools are necessary: their filesystem-based approach achieved 74.0% accuracy on the LoCoMo dataset (using GPT-4o mini), outperforming Mem0's graph variant at 68.5% [3]. The researchers concluded that well-designed agents with simple filesystem tools can perform well on retrieval benchmarks because agents effectively leverage filesystem operations from training data. However, this result must be contextualized by scale: filesystem approaches work well for bounded projects with dozens to hundreds of files but break down at hundreds of thousands of documents [9].

## Storage Formats and Git-Native Memory

### The Git Vault as Control Plane

Several projects now use Git as the versioning layer for agent memory, validating the architectural pattern CommandClaw requires:

**Letta Context Repositories (MemFS)** store agent context as local filesystem files version-controlled through Git. Every memory modification receives automatic version control with informative commit messages. The system supports concurrent operations across multiple subagents using separate Git worktrees, with conflict resolution through standard Git merge operations [4].

**DiffMem** takes a minimalist approach: memory stored as human-readable Markdown files in a Git repository, with the retrieval agent navigating the repository via shell commands (grep, git log, git diff, git show) like a developer would. No vector databases, embeddings, or BM25 are required -- Git's native diff system provides temporal queries cheaply [5].

**OpenViking** implements a tiered directory structure using the `viking://` URI scheme with L0 abstracts (~100 tokens), L1 overviews (~2K tokens), and L2 full content, loaded progressively based on retrieval relevance. Child L0 abstracts aggregate into parent L1 overviews, creating hierarchical navigation [12][39].

The common principle across all three is that **Markdown is the source of truth**. The vector index, when present, is a derived artifact that can always be rebuilt from the Markdown source. This ensures the git vault remains the single authoritative store while enabling fast semantic retrieval [32].

### Concurrency in Git-Native Memory

The dominant pattern for handling concurrent agent memory writes is Git worktrees. Each subagent receives an isolated worktree with its own working directory, branch, and staging area. When subagents complete their work, changes merge back through standard Git operations [4][29].

However, worktrees share more than expected: the .git object database, the lock file system, and any tracked files modified in parallel. This creates six distinct conflict types [29][31]. The Clash tool addresses this by performing read-only three-way merges to detect conflicts between worktree pairs before they happen, functioning as a pre-write hook [30].

For CommandClaw, the practical implication is that multi-agent memory access requires worktree-based isolation, with periodic merge-back operations. The memory compaction pattern from Letta -- reorganizing accumulated memories into 15-25 focused files during background "sleep-time" processes -- provides a model for maintaining vault hygiene without blocking active agents [4].

### Markdown File Structure

The optimal structure follows the progressive disclosure pattern: agents see directory structure in their system prompt and progressively load files as needed [9][12].

The recommended layout for a CommandClaw vault:

```
vault/
  MEMORY.md              # Hot tier: 200-line max, loaded every session
  memory/
    project-alpha.md     # Warm tier: topic files, indexed by vector search
    architecture.md
    decisions.md
  archive/
    2026-01.md           # Cold tier: monthly archives, git-searchable
    2026-02.md
```

The anti-pattern to avoid is a single monolithic MEMORY.md that grows unbounded. A 15,000-token memory file injected into every API call costs approximately $555/month at 100 daily requests. Over three months, such files accumulate contradictory preferences, stale projects, and inconsistent formats that actively degrade response quality [34].

## Vector Database Options

### Comparison for Local-First Deployment

For CommandClaw's local-first requirement, four embedded vector databases are worth evaluating [6][7][23][25]:

| Database | Architecture | RAM (idle/active) | Cost/month | Best For |
|----------|-------------|-------------------|------------|----------|
| LanceDB | Embedded, Lance columnar format | 4MB / 150MB | <$30 | Larger-than-memory datasets |
| ChromaDB | Embedded, in-process | Variable | <$30 | Rapid prototyping, best DX |
| SQLite-vec | SQLite extension, brute-force KNN | Minimal | $0 | Tiny corpora, extreme portability |
| Qdrant | Client-server, Rust | 400MB constant | $30-300 | Complex metadata filtering |

**LanceDB** runs in-process with zero-copy access to data via the Lance columnar format. It uses 4MB RAM when idle and ~150MB during search, scaling efficiently for larger-than-memory datasets without performance degradation. It is described as "basically the SQLite of vector dbs" [25]. For CommandClaw's use case -- moderate corpus size, local deployment, Python-native -- LanceDB is the strongest fit.

**ChromaDB** offers the best developer experience of any option, with a Python-native API that enables going from zero to a working prototype in minutes. Its 2025 Rust-core rewrite delivered 4x faster writes and queries [6]. However, it struggles with very large datasets (10M+ vectors) -- a limitation unlikely to matter at agent-memory scale.

**SQLite-vec** is a zero-dependency SQLite extension performing brute-force KNN searches. Performance at 100K vectors is sub-100ms, but at 1M vectors latency exceeds 100ms. The critical limitation is the lack of ANN indexing (no HNSW, no IVF), metadata filtering, or partitioned storage [7]. For CommandClaw's likely corpus size (under 100K chunks), SQLite-vec is viable but offers no growth path.

**Qdrant** provides superior metadata filtering and consistent latency from its Rust architecture, but requires Docker deployment and uses 400MB RAM constantly -- overkill for a personal/team agent platform [6][25].

A key perspective from the comparison literature: "Vector database selection represents perhaps 5-10% of RAG system quality. Chunking strategy, embedding model, retrieval pipeline, and prompt engineering matter far more" [6].

### Recommendation

For CommandClaw: **LanceDB** as the primary vector store. It is embedded (no server process), Python-native, lightweight, handles larger-than-memory datasets, and integrates well with the "derived index" pattern where the git-tracked Markdown remains the source of truth. ChromaDB is an acceptable alternative if developer experience during prototyping is prioritized.

## Embedding and Retrieval Strategies

### Local Embedding Model Selection

For a git-native agent platform that values local-first operation, the embedding model must run without cloud API dependencies. The 2026 landscape offers strong local options [16][24]:

| Model | MTEB Score | Dimensions | License | Notes |
|-------|-----------|------------|---------|-------|
| Qwen3-Embedding-8B | 70.58 | 7,168 | Apache 2.0 | Best quality, requires GPU |
| BGE-M3 | 63.0 | 1,024 | MIT | Dense + sparse + multi-vector |
| Nomic embed-text-v1.5 | ~62 | 768 | Apache 2.0 | Fully open, runs on Ollama |
| all-MiniLM-L6-v2 | 56.3 | 384 | Apache 2.0 | Sub-10ms CPU inference |

For comparison, OpenAI text-embedding-3-large scores 64.6 MTEB at $0.13/1M tokens [16]. The local models BGE-M3 and Nomic embed-text-v1.5 match or approach cloud API quality at zero marginal cost.

**BGE-M3** stands out because it supports dense, sparse, and multi-vector retrieval from a single model, making it particularly well-suited for hybrid search pipelines. It processes inputs up to 8,192 tokens and supports 100+ languages under MIT license [16][24].

**Nomic embed-text-v1.5** offers fully open weights, code, and training data under Apache 2.0. It runs on Ollama with 768 dimensions and 8K context, making it the most transparent option for a system where inspectability matters [16][24].

GGUF-quantized variants of these models enable CPU-only inference with approximately 92% quality retention. QMD's local stack demonstrates this is practical: three GGUF models totaling ~2GB (embedding ~300MB, re-ranker ~640MB, query expansion ~1.1GB) run entirely locally with no API keys [13][42].

### Matryoshka Embeddings and Dimensionality

Matryoshka Representation Learning (MRL) trains models to store important semantic information in earlier dimensions, allowing embeddings to be truncated without significant quality loss [36]. At 8.3% of full embedding size (64 out of 768 dimensions), Matryoshka-trained models preserve 98.37% of retrieval performance [36].

For agent memory at CommandClaw's scale (under 100K chunks), the bottleneck is not search speed or storage size but embedding quality and retrieval precision. The recommendation is to use full-dimension embeddings (768 or 1024) and reserve Matryoshka truncation as an optimization lever if latency or storage constraints emerge later. Binary quantization (1-bit embeddings) achieves up to 40x speed improvement but degrades accuracy unacceptably for embeddings under 1024 dimensions [37][38].

### Hybrid Retrieval Architecture

Hybrid search combines BM25 (sparse lexical retrieval) with dense vector retrieval in parallel, then merges results using a fusion algorithm [8]. This approach outperforms either method alone because dense retrieval misses exact keyword matches while sparse retrieval misses semantic synonyms.

**The Pipeline:**

1. **BM25 leg**: Ranks documents by term frequency and inverse document rarity. Excels at exact keyword matches, error messages, identifiers, and proper nouns [8].
2. **Vector leg**: Uses embedding similarity via ANN algorithms (e.g., HNSW) to find conceptually related documents regardless of term overlap [8].
3. **Fusion**: Reciprocal Rank Fusion (RRF) merges results based on rank position. Formula: RRF(d) = sum(1/(k + r(d))). Simple, requires no parameter tuning [8].
4. **Reranking** (optional): Cross-encoders or ColBERT re-score top candidates with a transformer for higher precision. Adds latency but improves quality on ambiguous queries [8].

**QMD as Reference Implementation.** OpenClaw's QMD combines all three methods -- BM25, vector semantic search, and LLM re-ranking -- in a single pipeline with three modes: `search` (BM25 only, instant), `vsearch` (vector only), and `query` (full hybrid with re-ranking, highest quality). It auto-indexes MEMORY.md and memory/**/*.md files, re-indexing every 5 minutes in the background [13].

**memsearch as Alternative.** The memsearch library (extracted from OpenClaw's memory system) demonstrates the "Markdown as source of truth" pattern: files are chunked by heading/paragraph boundaries, deduplicated via SHA-256, and indexed in Milvus. A file watcher auto-indexes on changes. It supports multiple embedding providers including ONNX (BGE-M3 int8, local CPU), Ollama, and cloud APIs [32][33].

## Session Lifecycle and Tiered Memory

### The Hot/Warm/Cold Model

The tiered memory pattern, borrowed from traditional storage architecture, has become the standard approach for agent memory management [9][18]. It promotes or demotes information based on relevance and access frequency:

**Hot Memory (System Prompt):** A curated `MEMORY.md` file (200-line maximum) loaded into every agent invocation. Inclusion test: "Will the next session break without this?" Contains current project state, active constraints, recent decisions, and next actions. Uses in-memory loading at the system prompt level (<1ms) [9].

**Warm Memory (Indexed Reference):** Topic-organized Markdown files in a `memory/` directory. Indexed by the vector search engine. Agent retrieves via hybrid search when hot memory is insufficient. Files are human-editable and git-versioned [9][13][32].

**Cold Memory (Archived History):** Monthly archive files (`archive/YYYY-MM.md`). Session transcripts and superseded decisions. Not indexed by default; searchable via git log/grep for historical investigation. Storage is cheap; retrieval is deliberate [9].

### The Consolidation Ritual

At session boundaries, agents execute a consolidation ritual [9]:

1. **Promote to hot**: If the next session requires it, update MEMORY.md
2. **Promote to warm**: If it has enduring reference value, create or update a topic file in `memory/`
3. **Archive to cold**: If it has historical value, compress to `archive/YYYY-MM.md`
4. **Discard**: Default action for most session scratchpad content

Then prune MEMORY.md back under the 200-line limit. This discipline prevents context obesity -- the gradual accumulation of stale, contradictory information that degrades agent performance [9][34].

### OpenViking's L0/L1/L2 Alternative

OpenViking proposes an orthogonal tiering model based on content granularity rather than temporal recency [12][39]:

- **L0**: One-sentence abstract (~100 tokens) for quick relevance assessment
- **L1**: Overview with core information (~2K tokens) for planning
- **L2**: Full original content for deep reading

Initial retrieval scans L0 abstracts across the memory hierarchy. High-scoring directories trigger L1 loading. L2 loads only when the agent explicitly requests it. This is complementary to hot/warm/cold -- one could apply L0/L1/L2 granularity within each temperature tier.

### Session Lifecycle Management

The Redis Agent Memory Server provides a well-specified lifecycle model [10]:

- **Formation**: Automatic background extraction (LLM analyzes conversations), batch storage (bundled with working memory updates), or direct API calls
- **Consolidation**: Working memory has automatic TTL (default 1 hour); promotion to long-term storage is explicit
- **Forgetting**: Age-based, inactivity-based, combined, or budget-based (retain only top N most recently accessed memories)
- **Compaction**: Periodic background tasks deduplicate memories and optimize search indexes

For CommandClaw, the session lifecycle maps to the git workflow: session start loads hot memory from MEMORY.md, the session writes to a scratchpad, and session end triggers the consolidation ritual with a git commit capturing all changes.

## Design Recommendations for CommandClaw

### Recommended Architecture

Based on the research, the recommended memory architecture for CommandClaw:

**Storage Layer:**
- Git-tracked Markdown vault as the single source of truth
- Three-tier file organization: MEMORY.md (hot), memory/*.md (warm), archive/*.md (cold)
- All memory changes committed to git with descriptive messages
- Git worktrees for concurrent agent access isolation

**Index Layer:**
- LanceDB as the embedded vector store (derived index, rebuildable from vault)
- Local embedding model: BGE-M3 (1024d, MIT) or Nomic embed-text-v1.5 (768d, Apache 2.0)
- File watcher for automatic re-indexing on Markdown changes
- SHA-256 content hashing to avoid re-embedding unchanged chunks

**Retrieval Layer:**
- Hybrid search: BM25 + vector search in parallel, fused via RRF
- Optional local reranker for ambiguous queries
- Three modes available: keyword-only (fast), semantic-only, full hybrid (highest quality)

**Session Layer:**
- Hot memory loaded into system prompt at session start
- Warm memory retrieved via hybrid search during session
- Consolidation ritual at session end: promote/archive/discard
- Automated MEMORY.md size enforcement (200-line limit)

### Key Trade-offs and Open Questions

**Filesystem simplicity vs. database reliability.** The architecture deliberately trades database guarantees (ACID, concurrent writes, access control) for inspectability and git-nativeness. This is appropriate at personal/team scale but would need revisiting for multi-tenant or enterprise deployment [14][20].

**Local embedding vs. cloud API.** Local models (BGE-M3 at 63.0 MTEB) trail the best cloud APIs (Qwen3-Embedding-8B at 70.58 MTEB, Voyage-3-large at ~67 MTEB) in quality. For agent memory where the corpus is small and domain-specific, the quality gap is likely smaller than benchmark numbers suggest, and the benefits of zero-cost, offline operation, and no data exfiltration risk outweigh it [16].

**Index rebuild cost.** The "derived index" pattern means the vector index can always be rebuilt from Markdown source, making corruption recoverable. However, full re-indexing of a large vault is slow (embedding is compute-bound). Incremental indexing via file watching and SHA-256 deduplication mitigates this for normal operation [32].

**Memory file proliferation.** As the vault grows from dozens to hundreds of files, the warm tier becomes harder to navigate. Periodic defragmentation (merging related files, splitting overgrown ones, targeting 15-25 focused files) is necessary to maintain retrieval quality [4][34].

## Discussion

The agent memory landscape in early 2026 shows a clear convergence toward hybrid architectures. The filesystem-vs-database debate has resolved not with a winner but with a layered answer: filesystem interface (what the agent sees) over database substrate (what enables fast retrieval) [14][22]. Git-native versioning has emerged as a strong pattern across multiple independent projects (Letta, DiffMem, OpenViking, Git Context Controller), validating the approach CommandClaw requires [4][5][12].

A productive tension exists between two camps. One camp, represented by Letta's benchmarks [3] and DiffMem's architecture [5], argues that simple filesystem operations are sufficient -- agents can navigate Markdown repositories with grep and git commands, achieving strong retrieval accuracy without vector databases. The opposing camp, represented by the MEMORY.md scaling analysis [34] and enterprise memory engineering [20], argues that filesystem-only approaches degrade predictably as memory grows due to token bloat, the attention dead zone effect, and concurrent write corruption.

The resolution is scale-dependent. For CommandClaw's target (personal/team, thousands of sessions), the filesystem-with-derived-index approach sits at the sweet spot. The Markdown vault provides inspectability and git-nativeness. The derived LanceDB index provides fast semantic retrieval. The tiered architecture (hot/warm/cold) prevents the context window pollution that kills filesystem-only approaches at scale. And because the index is always rebuildable from the vault, the system degrades gracefully -- worst case, you lose the index and rebuild it.

The embedding model selection is less consequential than it might appear. The gap between local models (BGE-M3 at 63.0 MTEB) and the best cloud models (70.58 MTEB) matters less for agent memory than for general-purpose RAG, because the corpus is small, domain-specific, and written by or for the agent itself. The hybrid retrieval pipeline (BM25 + semantic + reranking) compensates for embedding model limitations by combining complementary retrieval signals [8][13].

## Conclusion

The memory system for a git-native AI agent platform like CommandClaw should follow three principles:

1. **Markdown is the source of truth.** All memory lives as plain Markdown files in a git-tracked vault. The vector index is a derived artifact, always rebuildable. This ensures inspectability, editability, and versioning without sacrificing retrieval performance.

2. **Tiered architecture prevents context rot.** Strict hot/warm/cold tiers with automated size enforcement and a consolidation ritual at session boundaries keep the context window clean and relevant. The 200-line MEMORY.md limit is not a suggestion but an operational requirement.

3. **Hybrid retrieval compensates for scale.** BM25 catches exact matches that semantic search misses. Semantic search catches conceptual matches that BM25 misses. RRF fusion combines them without parameter tuning. A local reranker refines results when precision matters.

The concrete recommendation: LanceDB for vector storage, BGE-M3 or Nomic embed-text-v1.5 for local embeddings, a file-watcher-based incremental indexing pipeline, and git worktrees for concurrent agent access. This stack is fully local, fully inspectable, and fully versioned -- aligned with CommandClaw's core design constraint that the git vault is the control plane.

Open questions for future investigation include: optimal consolidation ritual automation (LLM-driven vs. rule-based promotion/demotion), the right defragmentation frequency and file count targets for warm memory, and whether OpenViking's L0/L1/L2 granularity model should be layered on top of the hot/warm/cold temperature model for additional token savings.

## References

See agent-memory-architecture-references.md for the full bibliography.
