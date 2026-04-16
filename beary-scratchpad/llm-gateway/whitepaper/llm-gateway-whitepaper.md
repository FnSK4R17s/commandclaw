# LLM Gateway for CommandClaw: Architecture, Alternatives, and Build-vs-Buy Analysis

**Author:** Background Research Agent (BEARY)
**Date:** 2026-04-15

---

## Abstract

This whitepaper evaluates the design space for adding an LLM gateway to the CommandClaw agent platform. It surveys the current landscape of open-source and managed LLM gateways (LiteLLM, Portkey, Bifrost, TensorZero, and others), distills the core design patterns required for production deployment (routing, fallbacks, rate limiting, cost tracking, caching, observability, credential management), and analyzes integration pathways with CommandClaw's existing LangChain/LangGraph runtime, Langfuse tracing, and commandclaw-mcp credential infrastructure. The paper concludes with three concrete architectural options ranked by implementation effort and capability, with a recommended hybrid approach: a thin custom FastAPI gateway using LiteLLM's Python SDK as a library for provider abstraction, deployed as a centralized service alongside the existing Docker Compose stack.

---

## Introduction

CommandClaw is a git-native AI agent platform where each agent runs in an isolated Docker container with a versioned vault mounted at `/workspace`. LLM calls currently flow through LangChain's `ChatOpenAI` with an optional `openai_base_url` override — a single passthrough that supports any OpenAI-compatible endpoint but provides no gateway-level routing, cost tracking, provider failover, or multi-tenant budget enforcement [1][2].

As the platform scales to support multiple agents, teams, and providers, the absence of a centralized LLM gateway creates several operational gaps:

- **No provider failover.** A single provider outage takes down all agents.
- **No cost visibility.** Token spend is invisible at the team/agent level.
- **No rate limiting.** A runaway agent can exhaust API quotas for all other agents.
- **No credential isolation.** Provider API keys are configured per-agent rather than managed centrally.
- **No caching.** Repeated identical prompts (common in agent loops) hit the provider every time.

This whitepaper investigates how to close these gaps by introducing an LLM gateway layer, evaluating whether to build a custom solution, adopt an existing open-source gateway, or pursue a hybrid approach.

---

## Background

### What Is an LLM Gateway?

An LLM gateway is a reverse proxy positioned between applications and LLM providers, providing a single managed interface for policy enforcement, routing, rate limiting, caching, cost governance, and observability [34][36]. It differs from a traditional API gateway in three critical ways: latency is seconds-to-minutes rather than milliseconds; billing is per-token rather than per-request; and security threats include prompt injection and PII leakage rather than standard injection/DDoS [36].

Three related but distinct primitives exist: a **gateway** (centralized control and security), a **router** (dynamic traffic distribution by complexity or cost), and a **proxy** (integration, compliance, and monitoring layer). Production systems typically combine all three [37].

### CommandClaw's Current Architecture

CommandClaw's LLM integration rests on three components:

1. **Agent Runtime** (`commandclaw/agent/`): LangGraph-based ReAct agent using `ChatOpenAI` with an optional `base_url` passthrough. All LLM traffic flows through LangChain's abstraction layer — no direct `openai` or `anthropic` SDK imports.

2. **MCP Credential Gateway** (`commandclaw-mcp`): A FastAPI + fastmcp service (port 8420) acting as a secure proxy for MCP tool servers. Agents hold short-lived phantom tokens and never see real API keys. Infrastructure: Redis-backed session pooling, Cerbos RBAC, OpenTelemetry + Prometheus instrumentation, hourly key rotation.

3. **Observability Stack** (`commandclaw-observe`): Docker Compose bundle with Langfuse v3 + ClickHouse + Postgres + Redis + MinIO for LLM tracing, plus Prometheus + Grafana for MCP gateway metrics.

The `base_url` passthrough means CommandClaw is already gateway-ready — pointing `ChatOpenAI` at a gateway URL requires zero agent code changes [46][48].

---

## The LLM Gateway Landscape

### LiteLLM: The Dominant Open-Source Gateway

LiteLLM (BerriAI, Y Combinator W23) is the leading open-source LLM gateway with 43,400 GitHub stars, 140+ provider support, and 240 million Docker pulls. Enterprise adopters include Stripe and Netflix [1][4].

**Architecture.** LiteLLM operates in two modes: a Python SDK (`litellm.completion()`) for in-process use, and a Proxy Server (FastAPI-based HTTP service) exposing OpenAI-compatible endpoints. The proxy uses PostgreSQL for persistence and Redis for distributed rate limiting, cooldown state, and caching [2][5][6].

**Routing.** The `Router` class implements multiple strategies: `simple-shuffle` (recommended for production), `least-busy`, `latency-based-routing`, and `cost-based-routing`. Weighted and ordered deployments enable priority tiers and gradual rollouts [7][8].

**Fallbacks.** Three specialized types: standard (any error), context window (auto-routes to larger model), and content policy (routes to different provider). Each fallback model group runs through the full routing pipeline independently [9].

**Multi-tenant.** Four-level hierarchy: Organizations, Teams, Users, Virtual Keys. Hierarchical budget enforcement is real-time: org budget, team budget, user budget. RBAC roles from Proxy Admin to Internal User [14].

**Limitations.** Python overhead adds hundreds of microseconds per request at 500+ RPS. PostgreSQL spend logging degrades performance without Redis batching. `usage-based-routing` is explicitly flagged as too slow for production. The Helm chart remains BETA. Docker Compose is inadequate for true HA [4][16].

### High-Performance Alternatives

| Gateway | Language | Overhead | Key Differentiator |
|---|---|---|---|
| **Bifrost** | Go | 11 us at 5,000 RPS | Native MCP support, OTel, 50x faster than LiteLLM [21][22] |
| **TensorZero** | Rust | <1ms P99 at 10,000 QPS | ClickHouse traces, GitOps config, 25-100x faster [22] |
| **Portkey** | TypeScript | <1ms claimed | 40+ guardrails, PII redaction, SOC2/HIPAA [24][27] |
| **Helicone** | Rust | 8ms P50 | Observability-first, PeakEWMA load balancing [18] |

### Managed Services

**OpenRouter** provides zero-infrastructure access to 400+ models with a 5% markup on provider rates and ~40ms overhead — suitable for individual developers but not for platform-level governance [23][19].

**Cloudflare AI Gateway** offers edge caching, logging, and rate limiting with a one-line integration, but lacks RBAC, budget enforcement, and self-hosting [30].

**Kong AI Gateway** extends the established Nginx-based API management platform with AI-specific plugins (semantic routing, guardrails, semantic caching), best suited for organizations already running Kong [22][31].

---

## Core Design Patterns

### Rate Limiting

Traditional requests-per-second rate limiting is insufficient for LLMs. Production gateways require multi-dimensional, token-aware enforcement [38][36]:

- **Dimensions:** per-key, per-team, per-model, per-request-type, per-region
- **Units:** RPM/RPD, TPM/TPD, budget caps in USD
- **Algorithms:** sliding window (Redis-backed) or token bucket for smooth throughput control
- **Cluster-wide consistency** requires a shared store (Redis) across multiple gateway nodes

### Routing and Fallbacks

Routing operates through a multi-stage filter pipeline: health filtering (remove cooldown deployments), strategy application (algorithm selection), and final selection [8][40].

Fallback patterns cascade after retry exhaustion: provider chains (OpenAI, Anthropic, Gemini), model-level degradation (GPT-4, GPT-3.5 within same vendor), and guardrail-triggered rerouting. Each fallback attempt runs the full plugin chain independently — errors on one provider do not leak state to the next [42][41].

The circuit breaker pattern (closed, open, half-open states) prevents cascading failures by blocking requests to consistently failing providers [42][40].

### Cost Tracking

Cost tracking must be multi-dimensional and real-time [34][40]:

- Token attribution: input tokens, output tokens, cached tokens — with per-model per-provider pricing tables
- The universal formula: `total_cost = (prompt_tokens / 1M) * prompt_price + (completion_tokens / 1M) * completion_price` [72][73]
- Budget enforcement with hard limits (block) or soft limits (alert)
- Streaming edge case: costs unknown until stream ends, requiring deferred accounting
- Aggregation by tenant, team, project, use case, and model

### Caching

- **Exact caching:** Full prompt hash as cache key. Zero-token cost on hit. Straightforward over any KV store [40].
- **Semantic caching:** Embedding similarity matches semantically equivalent queries. Tradeoff: embedding compute vs. API savings [35][36].
- **Provider-side prompt caching:** Anthropic/OpenAI discount repeated prefixes at ~10-20% of full price. Gateway cost accounting must handle cached vs. uncached token rates correctly [40].

### Observability

Three pillars, following OTel GenAI semantic conventions (`gen_ai.*` namespace) [81][82]:

- **Logging:** Request/response pairs with prompt text, latency, token counts, cost, error codes, tenant tags
- **Metrics:** TTFT, completion latency (P50/P95/P99), tokens/sec, error rate per model, cache hit rate, cost per tenant
- **Traces:** OTLP spans covering gateway ingress, routing decision, provider call, guardrail check, response post-processing

LiteLLM's Prometheus catalog provides a comprehensive reference: 30+ metrics covering tokens, spend, budget remaining, rate limit headroom, latency histograms (total, API-only, overhead, TTFT), deployment health state, and Redis performance [84].

### Security and Credential Management

Virtual keys (`sk-[alphanumeric]`) decouple client credentials from provider credentials. If compromised, revoke the virtual key without rotating provider secrets [85]. Keys carry constraints: `max_budget`, `budget_duration`, `tpm_limit`, `rpm_limit`, `models` allowlist. The hierarchy — Keys, Users, Teams — enables independent spend tracking at each level [85].

Redis serves seven distinct functions in a production gateway: rate limiting, response caching, spend aggregation queues, distributed coordination, credential storage, context/session persistence, and semantic routing [86][87].

---

## Integration with CommandClaw

### The `base_url` Passthrough

The integration mechanism is remarkably simple. CommandClaw's `ChatOpenAI(base_url=settings.openai_base_url)` already supports pointing at any OpenAI-compatible endpoint. Swapping from direct provider access to a gateway requires changing one configuration value — no agent code changes [46][48].

```python
# Current: direct to provider
llm = ChatOpenAI(base_url="https://api.openai.com/v1", api_key=real_key)

# With gateway: same interface, gateway handles routing
llm = ChatOpenAI(base_url="http://llm-gateway:4000", api_key=virtual_key)
```

Gateway metadata (tags, routing hints) can travel via `extra_body` without LangChain needing to understand them [47].

### Gateway-Level vs. Framework-Level Routing

These serve complementary purposes [49][57]:

- **Gateway-level** (HTTP boundary): provider selection, failover, cost routing, rate limiting. All agents benefit without code changes.
- **Framework-level** (LangGraph conditional edges): agent orchestration, state-dependent logic, multi-agent routing. Operates inside the reasoning loop with access to internal state.

A gateway cannot stop an agent's tool-calling loop — it can only intercept individual LLM HTTP calls. LangGraph's node/edge system provides the in-process equivalent [57].

### Observability Integration

CommandClaw already runs Langfuse for LLM tracing. The recommended production pattern pairs a synchronous gateway for routing/caching/keys with asynchronous SDK-level tracing for full observability [53]:

- **Gateway layer:** Langfuse callback (`litellm.success_callback = ["langfuse"]`) captures every LLM call with model, tokens, cost, and metadata [77]
- **Framework layer:** LangChain `BaseCallbackHandler` captures full execution context — chain steps, agent actions, tool outputs — which the gateway cannot see [50]
- **Prometheus:** Gateway metrics exported at `/metrics` feed into the existing Prometheus + Grafana stack in commandclaw-observe [84]

### Credential Management Reuse

CommandClaw-mcp already implements the virtual key pattern: agents hold phantom tokens, never see real API keys, Redis-backed session pooling, Cerbos RBAC. An LLM gateway can reuse this exact pattern — virtual LLM keys map to provider credentials, with per-key budget and model constraints [85][86].

---

## Building a Minimal Gateway

A minimal viable LLM gateway in Python/FastAPI requires approximately 500 lines of code [58][63]:

### Core Surface

```python
# POST /v1/chat/completions — required
# GET /v1/models — required for model enumeration
# POST /v1/embeddings — needed for RAG pipelines
```

### Provider Abstraction

```python
class BaseLLMProvider(ABC):
    @abstractmethod
    async def complete(self, messages, model, temperature=0.7, max_tokens=None) -> LLMResponse:
        pass
```

Concrete implementations handle provider-specific quirks. Provider dispatch uses model name prefix (`provider/model`) or glob pattern matching [63][58].

### SSE Streaming

```python
from fastapi.responses import StreamingResponse

async def generate():
    async for chunk in upstream_stream:
        yield f"data: {json.dumps(chunk.dict())}\n\n"
    yield "data: [DONE]\n\n"

return StreamingResponse(generate(), media_type="text/event-stream")
```

FastAPI v0.115+ ships native `EventSourceResponse` with auto keep-alive pings [71]. Must poll `request.is_disconnected()` to abort expensive generation early [61].

### Reference Implementations

- **lm-proxy** (Nayjest): TOML-configured routing, virtual keys, streaming, PyPI-published [58]
- **LLM-API-Key-Proxy** (Mirrowel): Multi-format (OpenAI + Anthropic native), multi-key with priority tiers [60]
- **deepset-ai/fastapi-openai-compat**: Router factory that handles streaming/non-streaming paths, auto-wraps strings into `chat.completion.chunk` [69]

---

## Deployment Architecture

### Centralized Gateway Pattern

CommandClaw runs 3+ services (agent runtime, MCP gateway, observability), making the centralized gateway pattern appropriate [88]. The gateway sits between agent runtimes and providers, discoverable via Docker Compose DNS:

```
[Agent Containers]
       | http://llm-gateway:4000
       v
[LLM Gateway (FastAPI)] <-- Redis (cache + rate limits)
       |                        |
       v                        v
[LLM Providers]          [PostgreSQL (spend)]
  OpenAI                        |
  Anthropic                     v
  Bedrock              [Prometheus scrape]
  Ollama                        |
                                v
                          [Grafana]
```

Service discovery via Docker Compose DNS — no external service mesh required [90][91].

### Unified LLM + MCP Gateway

The emerging pattern combines LLM routing and MCP tool access in a single process [94][95]. LiteLLM supports this: `/v1/chat/completions` for LLM routing and `/v1/mcp` for tool registry from the same container. Running separate gateways creates "operational complexity and governance gaps" [95].

For CommandClaw, the decision is whether to merge the LLM gateway into commandclaw-mcp (unified) or run it as a separate service (separated). The unified approach reduces infrastructure but increases the blast radius of a single failure. Given commandclaw-mcp's existing credential management and Redis infrastructure, a unified approach is architecturally natural but should be deferred until the LLM gateway is stable.

### Production Hardening

- Health checks with 120s `start_period` for model-serving containers [91]
- `depends_on: condition: service_healthy` for dependency ordering
- Docker secrets (not raw env vars) for credentials — env vars are visible via `docker inspect` [90]
- Named volumes for portability; message brokers for inter-agent communication [90]
- Prometheus multiproc: set `PROMETHEUS_MULTIPROC_DIR` for multi-worker deployments [84]

---

## Three Architectural Options

### Option A: Deploy LiteLLM Proxy as a Standalone Service

**Effort:** Low (days). Add a `litellm` container to Docker Compose with `config.yaml`. Point agent `base_url` at `http://litellm:4000`.

**Pros:**
- 140+ providers, battle-tested routing, virtual keys, admin UI out of the box
- Rich Prometheus metrics and Langfuse integration built in
- Active community (43,400 stars, 1,300+ contributors)

**Cons:**
- Adds PostgreSQL dependency (LiteLLM requires its own DB for key/spend storage)
- Python overhead (~3ms P50, 31ms P99) — acceptable for CommandClaw's current scale
- Separate infrastructure from commandclaw-mcp — duplicated Redis, auth, key management patterns
- Config surface area is large; operational complexity increases
- Salt key immutability creates a migration risk [4][16]

**Best for:** Fast deployment with full feature set. Accept the infrastructure duplication.

### Option B: Build a Thin Custom Gateway

**Effort:** Medium (1-2 weeks). FastAPI service (~500 lines) with ABC provider adapters, SSE streaming, Redis rate limiting, Langfuse `@observe` decorator, Prometheus counters.

**Pros:**
- Reuses commandclaw-mcp's FastAPI + Redis + Cerbos infrastructure
- No new PostgreSQL dependency — spend tracking in existing Redis or commandclaw's Postgres
- Full control over routing logic, credential management, and observability integration
- Tight alignment with commandclaw's existing patterns (phantom tokens, RBAC, vault structure)

**Cons:**
- Must implement provider adapters manually (or import litellm SDK as library)
- Limited provider breadth initially — must add adapters for each new provider
- No admin UI
- Ongoing maintenance burden for provider API changes

**Best for:** Maximum architectural coherence with the commandclaw ecosystem. Viable only if provider count stays small (<5).

### Option C: Hybrid — Custom FastAPI Gateway Using LiteLLM SDK as Library (Recommended)

**Effort:** Medium-low (1 week). FastAPI service that imports `litellm.completion()` and `litellm.Router` as a library, wrapped in commandclaw's auth/observability patterns.

**Pros:**
- Gets LiteLLM's 140+ provider support and routing logic without running its proxy server
- No additional PostgreSQL dependency — LiteLLM SDK mode does not require a database
- Reuses commandclaw-mcp's Redis, auth patterns, and infrastructure
- Custom endpoints expose commandclaw-specific features (vault integration, agent-scoped budgets)
- Langfuse integration via both LiteLLM callbacks and commandclaw's existing SDK tracing
- Prometheus metrics defined to match commandclaw-observe's existing dashboard patterns
- Full control over the API surface and deployment lifecycle

**Cons:**
- No admin UI (build or skip)
- Virtual key management must be implemented (but commandclaw-mcp's phantom token pattern is directly reusable)
- LiteLLM SDK updates may introduce breaking changes (pin versions)

**Architecture:**

```python
# commandclaw-gateway/main.py (conceptual)
from fastapi import FastAPI
from litellm import Router

app = FastAPI()
router = Router(model_list=load_config(), routing_strategy="simple-shuffle")

@app.post("/v1/chat/completions")
@observe(as_type="generation")
async def chat_completions(request: ChatRequest):
    # 1. Auth: validate virtual key (Redis lookup, reuse phantom token pattern)
    # 2. Rate limit: check TPM/RPM (Redis counters)
    # 3. Route: litellm Router handles provider selection, fallback, retry
    # 4. Stream: SSE via StreamingResponse
    # 5. Account: calculate cost, update budget (Redis queue -> Postgres batch)
    response = await router.acompletion(model=request.model, messages=request.messages)
    return response
```

**Best for:** The commandclaw ecosystem. Captures LiteLLM's provider breadth and routing maturity while maintaining architectural coherence with existing infrastructure.

---

## Discussion

### Build vs. Buy: The Key Tradeoff

The build-vs-buy decision matrix from the research [40] maps cleanly onto CommandClaw's situation:

| Component | Recommendation for CommandClaw |
|---|---|
| Provider abstraction | **Buy** (LiteLLM SDK) — 140+ providers is too much to replicate |
| Routing policies | **Buy** (LiteLLM Router) — battle-tested, configurable |
| Distributed rate limiting | **Build** over existing Redis — commandclaw-mcp already has the pattern |
| Virtual key management | **Build** — reuse phantom token infrastructure |
| Cost tracking | **Build** over Redis + existing Postgres — straightforward |
| Exact caching | **Build** — trivial over Redis |
| Observability | **Build** over existing Langfuse + Prometheus stack |
| Guardrails | **Defer** — add when needed, via LiteLLM callbacks or external service |

The hybrid approach (Option C) captures the "buy" items (provider abstraction, routing) as a library dependency while building the "build" items on top of existing commandclaw infrastructure. This avoids the infrastructure duplication of Option A and the provider-breadth limitation of Option B.

### Performance Considerations

LiteLLM's Python SDK adds overhead compared to Go/Rust alternatives (Bifrost at 11us, TensorZero at <1ms P99). However, CommandClaw's current workload is agent-driven, not high-throughput API serving. At agent-scale traffic (<100 concurrent agents, each making 1-10 LLM calls per minute), Python overhead is negligible relative to provider response times of 1-30 seconds [4][21].

If CommandClaw scales to a platform serving thousands of concurrent agents, migrating to Bifrost or TensorZero becomes warranted. The OpenAI-compatible API surface ensures this migration requires only changing the gateway implementation — no agent code changes.

### Unified vs. Separated Gateway

The research shows a trend toward unified gateways that handle both LLM routing and MCP tool access [94][95]. CommandClaw already separates these into commandclaw-mcp (tools) and the proposed LLM gateway (models). In the near term, keeping them separate reduces blast radius and allows independent scaling. In the medium term, consolidating into a single `commandclaw-gateway` service that handles both LLM routing and MCP tool mediation would reduce operational complexity and enable unified credential/budget management.

### What to Defer

Several capabilities are well-documented but not needed at CommandClaw's current scale:

- **Semantic caching** — adds embedding compute overhead; exact caching covers the common case (repeated system prompts in agent loops)
- **Content-based/semantic routing** — useful when running 5+ models with different capabilities; premature with 2-3 providers
- **Admin UI** — build or adopt when team size warrants it
- **Multi-region / control-plane-data-plane split** — enterprise pattern; defer until geographic distribution is needed [15]
- **Guardrails** (PII redaction, prompt injection) — add via LiteLLM callbacks or Bedrock Guardrails when compliance requires it

---

## Conclusion

CommandClaw needs an LLM gateway, and the integration path is clear. The existing `base_url` passthrough in `ChatOpenAI` means zero agent code changes. The existing commandclaw-mcp infrastructure (FastAPI, Redis, Cerbos RBAC, phantom tokens) provides the building blocks for credential management, rate limiting, and budget enforcement. The existing commandclaw-observe stack (Langfuse, Prometheus, Grafana) provides the observability layer.

The recommended approach is **Option C: a thin custom FastAPI gateway using LiteLLM's Python SDK as a library**. This captures LiteLLM's 140+ provider support and battle-tested routing logic while reusing CommandClaw's existing infrastructure. The gateway deploys as a centralized Docker Compose service at `http://llm-gateway:4000`, with agents connecting via the existing `base_url` configuration.

Implementation priorities:
1. Core gateway with `litellm.Router` for provider routing and fallbacks
2. Virtual key management reusing commandclaw-mcp's phantom token pattern
3. Redis-backed rate limiting (TPM/RPM per key)
4. Langfuse tracing via `@observe` decorator + LiteLLM callbacks
5. Prometheus metrics (tokens, spend, latency, deployment health)
6. Exact caching over Redis for repeated prompts
7. Cost tracking with per-agent budget enforcement

The 98-source research base confirms this approach balances engineering effort against capability. The gateway can be built in approximately one week, provides immediate value (failover, cost visibility, rate limiting), and leaves a clean migration path to higher-performance alternatives if CommandClaw's scale demands it.

---

## References

See [llm-gateway-references.md](llm-gateway-references.md) for the full bibliography (98 sources).
In-text citations use bracketed IDs, e.g., [1], [2].
