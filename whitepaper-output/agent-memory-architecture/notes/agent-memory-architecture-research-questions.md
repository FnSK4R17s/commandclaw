# Agent Memory Architecture — Research Questions

<!-- Research questions for the agent-memory-architecture topic. -->
<!-- See .agents/skills/beary/skills/internet-research/SKILL.MD for research workflow and guidelines. -->

## General Understanding

### Q1: What are the current approaches to persistent memory in AI agent systems, and how do filesystem-based memory hierarchies compare to database-backed approaches?

**Search terms:**
- AI agent persistent memory architecture 2025 2026
- filesystem-based memory hierarchy AI agents git-native
- agent memory storage comparison vector database vs filesystem

### Q2: What are the leading vector storage options for local-first AI agent memory, and how do SQLite-vec, LanceDB, ChromaDB, and Qdrant compare in performance and developer experience?

**Search terms:**
- SQLite-vec vs LanceDB vs ChromaDB vs Qdrant comparison 2025 2026
- local vector database embedded AI agent memory
- LanceDB SQLite-vec benchmark performance embedding storage

### Q3: How do hybrid retrieval strategies (BM25 + semantic search + reranking) work for agent memory retrieval, and what are the cost-performance tradeoffs?

**Search terms:**
- hybrid retrieval BM25 semantic search reranking AI agents
- agent memory retrieval strategy cost performance tradeoff
- RAG hybrid search BM25 vector reranking architecture 2025

### Q4: What are the emerging patterns for session lifecycle management and tiered memory (hot/warm/cold) in persistent AI agents?

**Search terms:**
- AI agent session lifecycle management persistent memory
- tiered memory hot warm cold AI agent architecture
- conversation session storage management AI agent platform 2025

---

## Deeper Dive

### Subtopic A: Git-Native Memory Storage for Agent Platforms

#### Q1: How do git-based memory systems (DiffMem, Letta Context Repos, OpenViking) handle concurrent writes, merge conflicts, and memory compaction in multi-agent scenarios?

**Search terms:**
- git-based agent memory concurrent writes merge conflicts worktrees
- Letta context repositories git worktrees subagent concurrency
- DiffMem OpenViking memory compaction defragmentation

#### Q2: What is the optimal Markdown-based memory file structure for a git-native agent vault, and how should files be organized to balance human readability with machine retrievability?

**Search terms:**
- agent memory markdown file structure organization best practices
- git vault agent memory file hierarchy inspectable editable
- OpenViking hierarchical context L0 L1 L2 directory structure

#### Q3: For a Python/LangChain agent platform where the git vault is the control plane, what are the practical integration patterns for combining git-native storage with vector search indexing?

**Search terms:**
- LangChain agent memory git integration vector index
- python agent platform git vault vector search sync
- memsearch markdown vector index git agent memory

### Subtopic B: Embedding Strategy and Local Model Selection

#### Q1: What are the best local/self-hosted embedding models for agent memory in 2026, and how do they compare to cloud APIs in quality, latency, and cost for small-to-medium corpora?

**Search terms:**
- best local embedding models agent memory 2026 nomic BGE ollama
- self-hosted embedding model vs OpenAI API cost latency comparison
- GGUF embedding model local inference performance benchmark

#### Q2: How should embedding dimensionality, quantization, and Matryoshka truncation be configured for agent memory use cases where the corpus is small (under 100K chunks) but retrieval precision is critical?

**Search terms:**
- embedding dimensionality quantization small corpus precision
- Matryoshka embedding truncation agent memory retrieval quality
- binary quantization vector search small dataset high precision

### Subtopic C: CommandClaw-Specific Design (Purpose-Driven)

#### Q1: Given a Python/LangChain agent where the git vault is the control plane and memory must be inspectable, editable, and versioned, what concrete architecture best combines tiered memory with hybrid retrieval?

**Search terms:**
- LangChain memory architecture inspectable editable versioned git
- agent memory design git control plane tiered retrieval
- CommandClaw OpenClaw agent vault memory architecture design

#### Q2: What are the failure modes and operational pitfalls of filesystem-based agent memory at the scale of a personal/team agent (thousands of sessions, tens of thousands of memory entries)?

**Search terms:**
- agent memory filesystem failure modes scale limitations
- personal AI agent memory scaling thousands sessions pitfalls
- filesystem agent memory performance degradation large history

---

## Redundant Questions

<!-- Move any redundant questions here during review. -->
