# commandclaw-memory-service — Research Questions

<!-- Research questions for the commandclaw-memory-service topic. -->
<!-- See .agents/skills/beary/skills/internet-research/SKILL.md for research workflow and guidelines. -->
<!-- Citations are stored in whitepaper/commandclaw-memory-service-references.md -->

## General Understanding

### Q1: How do leading agent platforms (LangGraph, AutoGPT, Letta/MemGPT, AutoGen, smolagents, Pydantic AI, Mastra, Goose) decompose their architecture — is the PERCEIVE→THINK→ACT→REMEMBER loop model correct, or are there better primitives?

**Search terms:**
- agent cognitive architecture primitives PERCEIVE THINK ACT REMEMBER loop 2026
- LangGraph AutoGPT Letta AutoGen agent architecture comparison primitives
- AI agent platform architecture decomposition effector perception memory substrate

### Q2: What is the architectural pattern used by dedicated agent memory services (Letta/MemGPT, Mem0, Zep, Cognee, Graphiti) — service vs embedded, tenancy model, API surface, distillation?

**Search terms:**
- Letta MemGPT memory service architecture API tenancy 2026
- Mem0 Zep Cognee Graphiti agent memory service vs embedded library
- agent memory service separate microservice vs embedded vector database

### Q3: What are the concrete trade-offs between LanceDB, Qdrant, Chroma, and pgvector at "dozens of agents, multi-year memory horizon" scale — and what are the RPC latency implications of externalizing the hot memory path?

**Search terms:**
- LanceDB Qdrant ChromaDB pgvector comparison latency scale 2026
- vector database RPC latency embedded vs client-server agent memory hot path
- vector database self-hosted single machine dozens agents performance

### Q4: What sync models exist for keeping a memory service consistent with a Git vault source of truth — and how do similar systems handle this (git commit hooks, file watchers, dual writes)?

**Search terms:**
- git commit hook trigger memory indexing sync pipeline 2026
- agent memory git vault sync dual write file watcher consistency
- event-driven memory indexing git hook post-commit webhook

---

## Deeper Dive

### Subtopic A: Five-Primitive Framing Validation

#### Q1: Do agent platforms outside the LangChain ecosystem (AutoGen, smolagents, Mastra, Inngest Agents, Pydantic AI) use a different architectural decomposition that would break or refine the five-primitive model?

**Search terms:**
- AutoGen smolagents Pydantic AI Mastra agent architecture internals 2026
- Inngest agent runtime architecture primitives perception action memory
- agent platform architecture survey comparison 2026

#### Q2: How do academic frameworks for cognitive architectures (SOAR, ACT-R, cognitive loop) map to or differ from the five-primitive model proposed for CommandClaw?

**Search terms:**
- SOAR ACT-R cognitive architecture AI agent loop memory perception action 2026
- cognitive architecture primitives AI agent system design academic
- perception action memory cognitive loop agent architecture theory

#### Q3: Is "substrate" a recognized architectural primitive in distributed systems or agent design, or is it conflating two concepts (state store + human interface)?

**Search terms:**
- agent substrate state management human-in-the-loop git control plane
- distributed systems substrate state store design pattern
- AI agent control plane audit trail git substrate architecture

### Subtopic B: Memory Service Architecture Deep Dive

#### Q1: How does Letta (MemGPT) architect its memory service internally — is it a separate process, embedded library, or MCP server — and what is its tenancy model?

**Search terms:**
- Letta MemGPT server architecture 2026 internal memory service API
- Letta agent server deployment docker tenancy multi-agent memory
- MemGPT memory service REST API architecture agent isolation

#### Q2: How do Zep, Cognee, Graphiti, and Mem0 differ in their distillation approach — who triggers distillation, what model, and is it synchronous or async background?

**Search terms:**
- Zep Cognee Graphiti distillation memory summarization architecture 2026
- Mem0 memory distillation LLM background async trigger
- agent memory consolidation distillation pipeline asynchronous

#### Q3: What auth model is appropriate for an internal memory service that handles no external credentials — is phantom token + HMAC overkill, or is mTLS / API key / no-auth the right default?

**Search terms:**
- internal microservice auth model memory service mTLS API key simple
- agent memory service authentication internal traffic security
- service mesh internal auth zero trust agent platform

### Subtopic C: Graceful Degradation and Failure Modes

#### Q1: What is the established pattern for graceful degradation when a memory service is unavailable — and how does this compare to the MCP gateway degradation pattern already built?

**Search terms:**
- graceful degradation memory service unavailable fallback agent
- circuit breaker pattern agent memory service failure
- agent memory fallback vault flat files service down

#### Q2: What are the migration patterns for bootstrapping a new vector memory service from existing flat Markdown files without data loss?

**Search terms:**
- migration flat markdown files vector database bootstrap 2026
- agent memory migration existing vault to vector database
- LanceDB bootstrap markdown files embedding migration pipeline

---

## Redundant Questions

<!-- None yet -->
