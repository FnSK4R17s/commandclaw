# LLM Gateway — Notes

<!-- Notes for the llm-gateway topic. Organized by question, not source. -->
<!-- Citations are stored in whitepaper/llm-gateway-references.md -->

## General Understanding

### Q1: What is the architecture and feature set of LiteLLM as the leading open-source LLM gateway/proxy?

LiteLLM is an open-source AI Gateway and Python SDK maintained by BerriAI (Y Combinator W23). It provides a unified OpenAI-compatible interface across 140+ LLM providers and 2,500+ models. As of April 2026, the project has approximately 43,400 GitHub stars, 7,300 forks, 20,000+ dependent projects, 1,300+ contributors, and 240 million Docker pulls. Enterprise adopters include Stripe and Netflix [1][4].

**Two Deployment Modes:**
- **Python SDK**: Library embedded in application code via `litellm.completion()` and the `Router` class. Good for prototyping.
- **Proxy Server (AI Gateway)**: Centralized FastAPI-based HTTP service exposing OpenAI-compatible endpoints (`/chat/completions`, `/embeddings`, etc.). Any OpenAI client works with zero code changes [2].

**Proxy Architecture:**
- FastAPI + Uvicorn ASGI server
- Router class (`litellm/router.py`) manages deployment selection, retry, fallback, and cooldown
- PostgreSQL for persistence (virtual keys, user/team/org metadata, spend tracking, audit logs)
- Redis for distributed rate limiting (TPM/RPM), cooldown state sharing, response caching
- Admin UI for key management, spend visibility, model configuration
- Separate health check app on port 8001 for K8s probes [2][5][6]

**Routing Strategies:**
| Strategy | Description | Production Notes |
|---|---|---|
| `simple-shuffle` | Randomized with RPM/TPM weights | Recommended for production |
| `least-busy` | Fewest concurrent requests | Good for spike absorption |
| `latency-based-routing` | Routes to lowest recent latency | Includes buffer to avoid overloading |
| `usage-based-routing-v2` | Routes to lowest usage | Not recommended — adds Redis latency |
| `cost-based-routing` | Cheapest available deployment | Uses LiteLLM cost map |
| Custom | `CustomRoutingStrategyBase` | Full custom logic [7][8] |

**Fallback Mechanisms:**
- Standard fallbacks (any error after retries exhausted)
- Context window fallbacks (`ContextWindowExceededError` → larger-context model)
- Content policy fallbacks (`ContentPolicyViolationError` → different provider) [9]

**Retry and Cooldown:**
- Configurable `num_retries` per deployment
- Exponential backoff for rate limits; immediate retry for generic failures
- Default cooldown: 3 failures/min → 5-second cooldown
- Non-retryable errors (401, 404, 408) trigger immediate cooldown
- Pre-call checks validate context window before sending [7][8]

**Multi-Tenant Architecture:**
- Four-level hierarchy: Organizations → Teams → Users → Virtual Keys
- Hierarchical budget enforcement (org → team → user)
- RBAC: Proxy Admin → Org Admin → Team Admin → Internal User [14]

**Production Deployment:**
- Minimum: 4 vCPU, 8 GB RAM per instance
- Docker (`-stable` tags passed 12-hour load tests), Kubernetes, Helm (BETA), Terraform
- Workers = CPU count; `--max_requests_before_restart 10000`
- DB pool formula: `MAX_DB_CONNECTIONS / (instances * workers)` [11][12]

**Known Limitations:**
1. Python overhead — hundreds of microseconds per request at 500+ RPS
2. DB bottleneck — spend logging to PostgreSQL; requires Redis batching
3. Cold start delays from large package import surface
4. Cache staleness — TTL validation must be carefully tuned
5. Provider feature heterogeneity across 140+ providers
6. `usage-based-routing` too slow for high-traffic production
7. Helm chart still BETA
8. `redis_url` vs discrete params: ~80 RPS penalty
9. Salt key immutability — no migration path if changed
10. Docker Compose insufficient for true HA — K8s required [4][16]

---

### Q2: What alternative LLM gateway/proxy solutions exist and how do they compare?

**Taxonomy:** An LLM proxy operates locally for individual developers (cost tracking, caching). An LLM gateway is enterprise infrastructure for organizational-scale governance (multi-team RBAC, SSO, audit trails, policy enforcement) [20].

**Performance Benchmarks:**
- Bifrost (Go): 11 microseconds overhead at 5,000 RPS — 50x faster than LiteLLM
- TensorZero (Rust): <1ms P99 at 10,000 QPS — 25-100x lower latency than LiteLLM
- Helicone (Rust): 8ms P50, horizontally scalable
- LiteLLM (Python): ~3ms P50, 17ms P90, 31ms P99
- Portkey (TypeScript): <1ms claimed, 122kb binary [21][22][23]

**Major Alternatives:**

**Portkey** (TypeScript, MIT core, 11,300 stars): 250+ providers, 40+ built-in guardrails (PII redaction, jailbreak detection), virtual keys, RBAC, SSO/SCIM, prompt versioning, semantic caching, MCP registry. SOC2/HIPAA/GDPR compliant. Free tier (10K logs/month), $49+/mo production. Differentiator: production safety and governance vs. LiteLLM's routing breadth [24][27].

**OpenRouter** (closed-source, managed SaaS): 400-500+ models, zero infra setup. 5% markup on provider rates. ~40ms gateway overhead. Best for individual devs who want simplicity over control [23][19].

**Cloudflare AI Gateway** (closed-source, managed edge): One-line integration (change base_url). Caching, logging, cost analytics, rate limiting, retries, fallbacks. Free tier available. Narrow provider support but trivially easy. No RBAC or budget enforcement [30].

**Kong AI Gateway** (Nginx-based plugins, partial OSS): AI Semantic Routing, guardrails, semantic caching, token-based rate limiting. Best for orgs already running Kong for API management [22][31].

**MLflow AI Gateway** (Python, Apache 2.0): Part of MLflow ecosystem. Centralized key management, traffic splitting, failover chains, full request/response tracing. Fewer providers than LiteLLM. Best for Databricks/MLflow shops [32][33].

**Helicone** (Rust, OSS): Observability-first gateway. PeakEWMA load balancing, semantic caching, granular cost attribution. Often used alongside LiteLLM [18].

**TensorZero** (Rust, OSS): Ultra-high-throughput. ClickHouse for traces/metrics. GitOps-oriented. Best for latency-critical workloads [22].

**Bifrost** (Go, OSS): Native MCP support, OpenTelemetry observability, automatic failover. Best for Go-native teams needing extreme throughput [21][22].

**Comparative Table:**
| Tool | Language | OSS | Stars | Latency | Best For |
|---|---|---|---|---|---|
| LiteLLM | Python | Yes | 43,400 | ~3ms P50 | Routing breadth, full control |
| Portkey | TS | Partial | 11,300 | <1ms | Guardrails, compliance |
| OpenRouter | Closed | No | N/A | ~40ms | Zero-infra simplicity |
| Cloudflare | Closed | No | N/A | Edge | Cloudflare ecosystem |
| Kong | Nginx | Partial | N/A | Low | Existing Kong users |
| MLflow | Python | Yes | N/A | Moderate | MLflow/Databricks |
| Helicone | Rust | Yes | ~5,500 | 8ms P50 | Observability + analytics |
| TensorZero | Rust | Yes | Small | <1ms P99 | Ultra-high throughput |
| Bifrost | Go | Yes | Small | 11us | Go-native, MCP |

---

### Q3: What are the core design patterns and capabilities required for a production LLM gateway?

**What distinguishes an LLM gateway from a traditional API gateway:**
- Latency is seconds-to-minutes, not milliseconds
- Billing is per-token, not per-request
- Security threats include prompt injection and PII leakage [36]

**Three related primitives:** Gateway (centralized control + security), Router (dynamic traffic distribution), Proxy (integration + compliance + monitoring). Production systems combine all three [37].

**Rate Limiting — Multi-dimensional, token-aware [38][36]:**
- Dimensions: per-key, per-org/team, per-model, per-request-type, per-region
- Units: RPM/RPD, TPM/TPD, budget caps in dollars
- Algorithms: fixed window, sliding window (Redis-backed), token bucket/leaky bucket
- Cluster-wide consistency requires shared store (Redis) [38][35]

**Caching:**
- Exact (hash-based): full prompt hash → cached response. Zero-token cost on hit. Simple over any KV store [40].
- Semantic: embedding similarity matches lexically different but semantically equivalent queries. Tradeoff: embedding compute overhead vs. API savings [35][36].
- Provider-side prompt caching: Anthropic/OpenAI discount repeated prefixes at ~10-20% of full price. Gateway cost accounting must handle this correctly [40].

**Cost Tracking:**
- Token attribution: input, output, cached — with per-model per-provider pricing tables
- Aggregation by tenant, team, project, use case, prompt version, model
- Budget enforcement: hard limits (block) or soft limits (alert)
- Streaming edge case: costs unknown until stream ends → deferred accounting [34][40]

**Retry Patterns:**
- Retryable: 429, 500, 502, 503, 504. Non-retryable: 400, 401, 403, 404
- Exponential backoff with jitter (prevents thundering herd)
- Parse `Retry-After` and `X-RateLimit-Reset` headers
- Configurable per-provider retry budgets [42]

**Fallback Patterns:**
- Provider chains: OpenAI → Anthropic → Gemini → Azure
- Model-level degradation: GPT-4 → GPT-3.5 within same vendor
- Guardrail-triggered: different model when safety flags fire
- Status-code-triggered: 429 → immediate reroute (not retry) [42][41]

**Circuit Breaker:**
- Closed → Open → Half-Open states
- Prevents cascading failures by blocking requests to consistently failing providers
- Parameters: failure threshold, timeout duration, success threshold, rolling window [42][40]

**Routing Strategies:**
- Static (fixed mapping), weighted distribution, least-latency/adaptive, content-based/semantic, cost-based, hedged requests (speculative parallel calls) [40][41]

**Observability — Three Pillars:**
- Logging: request/response pairs, latency, tokens, cost, error codes, tenant tags
- Metrics: TTFT, completion latency (P50/P95/P99), tokens/sec, error rate, cache hit rate, cost/time/tenant
- Traces: OpenTelemetry spans covering gateway ingress → routing → provider call → guardrails → post-processing → cache [35][43]

**Security:**
- Virtual key management (clients never see provider API keys)
- JWT/API key auth at ingress; SSO/SAML for operators
- RBAC: per-key model allow-lists
- Prompt injection detection, PII redaction (pre and post), content moderation
- Prompt template enforcement (reject non-conforming requests) [36][40][45]

**Guardrails (Input/Output):**
- Input: prompt injection detection, PII detection/redaction, content policy, schema validation, token budget pre-check
- Output: toxicity classification, PII in response, factual grounding, format validation
- Streaming: must buffer chunks for sentence/JSON validation → adds latency [36][40]

**Build vs. Buy Matrix:**
| Component | Recommendation |
|---|---|
| Provider abstraction adapters | Build — thin, domain-specific |
| Routing policies | Build — business logic varies |
| Distributed rate limiting | Buy — Redis + existing solutions |
| Token accounting | Build over off-shelf KV store |
| Exact caching | Build — straightforward over KV |
| Semantic caching | Buy or use built-in gateway support |
| Workflow orchestration | Buy — durable execution is hard |
| Guardrails | Buy (Bedrock Guardrails, LlamaGuard) [40] |

---

### Q4: How do LLM gateways integrate with agent frameworks like LangChain/LangGraph?

**Core Integration: `base_url` passthrough.** Every `ChatOpenAI` constructor accepts a `base_url` parameter replacing the default endpoint. Any OpenAI-compatible gateway becomes accessible by changing one argument. Agent code does not change [46][48].

```python
client = ChatOpenAI(base_url="http://gateway:4000", model="gpt-4", api_key="virtual-key")
```

When the gateway handles model selection, `model=""` and `api_key="dummy"` are valid — the gateway config specifies the upstream provider [46]. Custom headers (e.g., gateway API keys) via `default_headers` [48].

**LiteLLM Two Integration Modes:**
1. **ChatLiteLLM (direct)**: Embeds routing logic inside LangChain call stack. No separate proxy. Good for development [47].
2. **ChatOpenAI → LiteLLM Proxy**: Centralized service. All routing, caching, rate limiting, spend tracking happens in the proxy. Application is unaware. `extra_body` passes metadata (tags, routing hints) through to the proxy [47][52].

**Proxy vs. Async Observability (Langfuse's framing):**
- Synchronous proxy (LiteLLM, Kong): adds latency, becomes SPOF, but provides caching, key management, routing
- Asynchronous SDK (Langfuse): zero latency overhead, no uptime dependency, captures full traces including chains/tools/retrieval
- Recommended production pattern: proxy for routing/caching/keys + async SDK for traces [53][54]

**LangChain Callbacks:** `BaseCallbackHandler` fires on `on_llm_start`, `on_llm_end`, `on_chain_start`, `on_tool_start`, etc. Captures full execution context (chain steps, agent actions, tool outputs) that a gateway cannot see — gateway only intercepts the HTTP boundary [50].

**Gateway-Level vs. Framework-Level Routing:**
- **Gateway-level** (Kong, LiteLLM): HTTP boundary. Semantic routing via embeddings, rate limiting, key governance, cost routing, failover. All teams benefit without code changes [49].
- **Framework-level** (LangGraph conditional edges, Router chains): Inside agent reasoning loop. Routes between specialized agents/subgraphs based on state. Inspects tool outputs, intermediate LLM decisions [56].
- These are complementary, not competing [49][55].

**Framework Middleware vs. Gateway Middleware:**
- Gateway middleware: operates at HTTP boundary. Can intercept individual LLM HTTP calls. Cannot stop an agent's tool-calling loop.
- Framework middleware (e.g., Microsoft Agent Framework): operates within reasoning loop. Can intercept between LLM steps, modify state, terminate reasoning mid-flight. Three layers: Agent (turn), Function (tool), Chat (model call) [57].
- LangGraph's node/edge system provides analogous capability for LangGraph agents.

**Integration Architecture Map:**
| Layer | Mechanism | What It Can Do |
|---|---|---|
| Network/HTTP | `base_url` override | Key mgmt, rate limiting, caching, routing, failover |
| Framework Callback | `BaseCallbackHandler` | Full trace capture including chains, tools, retrieval |
| In-process (turn) | Agent middleware / LangGraph nodes | Security screening, audit, terminate loop |
| In-process (tool) | Function middleware | Argument validation, budget enforcement |
| In-process (model) | Chat middleware / ChatLiteLLM | Token limits, per-call caching |
| Auth/Credential | JWT proxy (Envoy) | Provider credential injection, actor traceability [50] |

---

### Summary

The LLM gateway landscape has matured significantly by 2026. LiteLLM dominates the open-source space with 43,400 GitHub stars and 140+ provider support, but carries Python overhead that limits throughput at scale [1][4]. High-performance alternatives in Go (Bifrost, 11us overhead) and Rust (TensorZero, <1ms P99) exist for latency-critical workloads [21][22]. Portkey differentiates on production safety with 40+ built-in guardrails [24].

A production LLM gateway requires fundamentally different design from a traditional API gateway: token-aware rate limiting, per-model cost accounting, prompt injection defense, and PII redaction [36][38]. The core design patterns — multi-stage routing pipelines, exponential backoff with jitter, provider chain fallbacks, and circuit breakers — are well-established and documented [40][42].

For LangChain/LangGraph integration, the `base_url` passthrough is the dominant pattern — any OpenAI-compatible gateway integrates with zero framework code changes [46]. Gateway-level routing (provider selection, failover, cost) and framework-level routing (agent orchestration, state-dependent logic) serve complementary purposes and should coexist [49][57]. The recommended production stack pairs a synchronous gateway for routing/caching/keys with asynchronous SDK-level tracing for full observability [53].

A key tension emerges: LiteLLM's broad provider support and rich feature set come at the cost of Python performance overhead, while leaner alternatives sacrifice breadth for speed. For the commandclaw ecosystem specifically — which already uses LangChain/LangGraph with `ChatOpenAI(base_url=...)` and has Langfuse tracing in place — the decision reduces to whether to deploy LiteLLM as a sidecar gateway, build a thin custom gateway leveraging existing infrastructure (commandclaw-mcp's FastAPI + Redis stack), or adopt a lighter-weight alternative like Bifrost or TensorZero.

---

## Deeper Dive

### Subtopic 1: Building a Minimal LLM Gateway in Python (FastAPI)

#### Q5: What does a minimal viable LLM gateway look like in Python with FastAPI?

**Minimal OpenAI-compatible surface** (what clients expect):
- `POST /v1/chat/completions` — required, core endpoint
- `GET /v1/models` — required for clients that enumerate models
- `POST /v1/embeddings` — needed for RAG pipelines
- `POST /v1/completions` — legacy, optional [58]

**Provider abstraction pattern** — ABC-based interface [63]:
```python
class BaseLLMProvider(ABC):
    @abstractmethod
    async def complete(self, messages, model, temperature=0.7, max_tokens=None) -> LLMResponse:
        pass
```
Supporting dataclasses: `ChatMessage(role, content)` and `LLMResponse(content, model, provider, input_tokens, output_tokens)`. Concrete implementations handle provider-specific quirks (e.g., Anthropic treats system messages as a separate top-level field) [63].

**Provider dispatch**: model name prefix (`provider/model`) or glob pattern matching routes to adapter instances. LM-Proxy uses TOML routing rules: `"gpt*" = "openai.*"`, `"claude*" = "anthropic.*"` [58][59].

**Configuration**: Environment variables for API keys (never hardcoded), TOML/YAML for routing rules and connections. Virtual/proxy keys separate from upstream keys [58].

**Authentication middleware** — SHA-256 hashed key lookup [61]:
```python
async def verify_api_key(request: Request):
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    user = await lookup_user_by_key_hash(key_hash)
```

**Token-aware rate limiting** via Redis with per-minute and per-day windows [61].

**Three deployment topologies** [64]:
1. **Sidecar proxy** — library or local sidecar per service; lowest latency, no cross-service visibility. Use for <3 services.
2. **Centralized gateway** — dedicated service for all LLM traffic; full observability. Use for 3+ services.
3. **Edge routing** — geographic/compliance routing for data residency.

**Notable open-source minimal gateways:**
- **lm-proxy** (Nayjest): TOML-configured routing, virtual keys, streaming, PyPI-published [58][59]
- **LLM-API-Key-Proxy** (Mirrowel): Multi-format (OpenAI + Anthropic native), multi-key with priority tiers, per-provider quota groups [60]

#### Q6: How do existing gateways implement provider adapters, streaming, and token counting?

**LiteLLM's BaseConfig adapter pattern** — every provider represented by a class in `litellm/llms/<provider>/chat/transformation.py` implementing [66][67]:
- `validate_environment()` — sets HTTP headers, validates API keys
- `get_complete_url()` — constructs endpoint URL
- `transform_request()` — converts OpenAI format → provider wire format
- `transform_response()` — maps provider response → `ModelResponse` (OpenAI shape)
- `get_sync_custom_stream_wrapper()` — optional, for non-standard streaming

Adding a new provider requires edits to 4 files: `__init__.py`, `main.py`, `constants.py`, `get_llm_provider_logic.py`. OpenAI-compatible providers need only a JSON config — no Python adapter [66].

**SSE streaming in FastAPI** [70][71]:
```python
from fastapi.responses import StreamingResponse

async def generate():
    async for chunk in upstream_stream:
        yield f"data: {json.dumps(chunk.dict())}\n\n"
    yield "data: [DONE]\n\n"

return StreamingResponse(generate(), media_type="text/event-stream")
```
FastAPI v0.115+ ships native `EventSourceResponse` with auto keep-alive pings and `X-Accel-Buffering: no` header [71]. Critical: must poll `await request.is_disconnected()` to abort expensive generation early [61].

**Token counting** — three approaches [68][72][73]:
1. **tiktoken** (OpenAI models): `tiktoken.encoding_for_model("gpt-4o")` selects correct BPE encoding
2. **Anthropic beta API**: exact counts for Claude 3+
3. **tokencost library**: covers 400+ models with tiered strategy; offline pricing table

**Cost formula** [72][73]:
```
total_cost = (prompt_tokens / 1M) * prompt_price + (completion_tokens / 1M) * completion_price
```
ChatML overhead: each message adds ~4 tokens for role formatting markers + 2 tokens for reply primer [73].

---

### Subtopic 2: Integration with Existing CommandClaw Infrastructure

#### Q7: How can an LLM gateway integrate with Langfuse, Prometheus/OTel, and credential management?

**Three Langfuse integration approaches** [74][76]:
1. **OpenAI SDK wrapper**: `from langfuse.openai import openai` — drop-in, zero code changes
2. **`@observe` decorator**: wraps arbitrary functions with `as_type="generation"` for LLM calls; manual token counts via `update_current_observation(usage_details=...)` [76][78]
3. **Context manager**: most explicit control for gateway middleware [76]

**LiteLLM → Langfuse** via callback config: `litellm.success_callback = ["langfuse"]`. Metadata per request: `trace_id`, `trace_user_id`, `session_id`, `tags`, `generation_name`. Newer OTLP path: `callbacks: ["langfuse_otel"]` [77][79].

**OTel GenAI semantic conventions** (`gen_ai.*` namespace) [81]:
- Span naming: `{gen_ai.operation.name} {gen_ai.request.model}`
- Required: `gen_ai.operation.name`, `gen_ai.provider.name`
- Token attributes: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`
- Full prompt/completion payloads on span *events*, not attributes (avoid overwhelming backends) [82]

**LiteLLM Prometheus metrics** (enable: `callbacks: ["prometheus"]`, endpoint: `GET /metrics`) [84]:
- Token counters: `litellm_input_tokens_metric`, `litellm_output_tokens_metric`
- Spend: `litellm_spend_metric` (USD)
- Budget gauges: `litellm_remaining_team_budget_metric`, `litellm_remaining_api_key_budget_metric`
- Latency histograms: `litellm_request_total_latency_metric`, `litellm_llm_api_latency_metric`, `litellm_llm_api_time_to_first_token_metric`
- Deployment health: `litellm_deployment_state` (0=healthy, 1=partial, 2=outage)
- System: `litellm_redis_latency`, `litellm_in_flight_requests` [84]

**Virtual key architecture** [85]:
- Keys (`sk-[alphanumeric]`) decouple client credentials from provider credentials
- PostgreSQL stores key metadata, Redis provides high-speed rate-limit counters
- Per-key constraints: `max_budget`, `budget_duration`, `tpm_limit`, `rpm_limit`, `max_parallel_requests`, `models` allowlist
- Hierarchy: Keys → Users → Teams. Spend tracked independently at each level
- Spend writes batched in Redis queues, flushed to PostgreSQL periodically [84][85]

**Redis roles in gateway stack** [86][87]:
1. Rate limiting (atomic counters with window expiry)
2. Response caching (exact-match and semantic via RedisVL)
3. Spend aggregation queues (batch DB writes)
4. Distributed coordination (pod lock management)
5. Credential storage (with Vault as secrets engine)
6. Context/session persistence
7. Semantic routing (vector similarity for model selection)

#### Q8: What are the deployment patterns alongside MCP servers and agent runtimes?

**Sidecar vs. centralized** — scale-based heuristic: <3 services → sidecar, 3+ → centralized gateway [88]. Sidecar latency: microseconds over loopback. Centralized: full cross-service visibility and cost tracking [88][89].

**MCP Bridge architecture** (arXiv 2504.08999) — four-tier [93]:
1. Client applications (any REST client)
2. REST API layer (`/servers/{id}/tools/{toolName}`)
3. MCP Bridge proxy (connection pooling, heartbeat, reconnection)
4. MCP servers (STDIO and SSE transports)

Three-tier security for tool execution: Level 1 (standard), Level 2 (confirmation with token validation), Level 3 (isolated Docker container) [93].

**LiteLLM as unified LLM + MCP gateway** — single process handles `/v1/chat/completions` (LLM routing) and `/v1/mcp` (tool registry). Supports Streamable HTTP, SSE, and stdio MCP transports. Per-server auth, team-scoped access control [94].

**Docker-native MCP gateway** (`docker/mcp-gateway:latest`) — mounts Docker socket for on-demand MCP server container spawning [90].

**Production Docker Compose stack pattern** [91]:
```
[Agent Runtime] → [LLM Gateway (LiteLLM/Bifrost)] ← Redis
                        ↓                              ↓
                  [PostgreSQL]              [Prometheus scrape]
                        ↓                              ↓
              [LLM inference: vLLM/Ollama]        [Grafana]
                        ↓
              [Langfuse + ClickHouse + MinIO]
```
Service discovery via Docker Compose DNS — no external service mesh needed [90][91].

**Unified vs. separated gateway question**: Bifrost and AgentGateway take the unified approach (one binary: LLM routing + MCP tool access). Running separate gateways creates "operational complexity and governance gaps" [95]. LiteLLM supports both but is typically LLM-only with MCP added via config [94].

**Key production patterns** [90][91]:
- Health checks with 120s `start_period` for model containers
- `depends_on: condition: service_healthy` for dependency ordering
- Docker secrets (not raw env vars) for credentials
- Message brokers (Redis/RabbitMQ) for inter-agent communication — never shared volumes
- Named volumes (not bind mounts) for portability

---

### Summary

The deeper dive research reveals that building a minimal LLM gateway in Python/FastAPI is straightforward — the core pattern is a ~200-line FastAPI server exposing OpenAI-compatible endpoints with an ABC-based provider abstraction, SSE streaming via `StreamingResponse`, and TOML/YAML routing config [58][63][70]. Multiple open-source reference implementations exist (lm-proxy, LLM-API-Key-Proxy, deepset-ai/fastapi-openai-compat) that demonstrate the pattern is production-viable [58][60][69].

The integration story with commandclaw's existing infrastructure is particularly strong. The commandclaw-mcp service already runs FastAPI + Redis on the same architectural pattern a gateway needs [86][87]. Langfuse integration requires only the `@observe` decorator or OpenAI SDK wrapper — both trivial to add [74][76]. Prometheus metrics follow LiteLLM's well-documented catalog with standardized label dimensions [84]. The OTel GenAI semantic conventions provide a future-proof schema for LLM-specific trace attributes [81].

For deployment, the centralized gateway pattern (commandclaw already runs 3+ services) fits naturally into the existing Docker Compose stack. The gateway would sit between agent runtimes and providers, discoverable via Docker DNS at `http://llm-gateway:4000` [88][91]. The unified LLM + MCP gateway approach (one process handling both LLM routing and tool access) reduces operational complexity vs. running separate infrastructure [94][95].

The build-vs-buy tradeoff crystallizes around commandclaw's specific constraints: commandclaw already has FastAPI, Redis, Langfuse, and a virtual-key credential pattern in commandclaw-mcp. A thin custom gateway (~500 lines) that reuses this infrastructure would integrate more tightly than deploying LiteLLM as a separate service with its own PostgreSQL dependency. However, LiteLLM's 140+ provider support and battle-tested routing logic represent significant engineering effort to replicate. The hybrid approach — using LiteLLM's Python SDK (not the proxy server) as a library inside a custom FastAPI gateway — captures both benefits [47][64].
