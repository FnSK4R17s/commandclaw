# LiteLLM Feature Inventory and Build-Scope Estimation for CommandClaw

**Author:** Background Research Agent (BEARY)
**Date:** 2026-04-16

---

## Abstract

This whitepaper decomposes every documented feature of LiteLLM — the dominant open-source LLM gateway — into a structured inventory organized by functional domain. For each domain, it estimates the engineering effort required to build an equivalent from scratch, identifies which features CommandClaw actually needs, and flags features that can be deferred or skipped entirely. The inventory covers 37 documentation pages and catalogs approximately 400+ distinct features across 14 functional domains. The conclusion: CommandClaw needs roughly 15% of LiteLLM's feature surface, concentrated in 4 domains, buildable in ~2 weeks without importing LiteLLM as a dependency.

---

## 1. API Surface — Supported Endpoints

LiteLLM exposes an enormous endpoint surface that has grown well beyond LLM completion proxying [3]:

### Endpoints CommandClaw Needs

| Endpoint | Purpose | Build Effort |
|---|---|---|
| `POST /v1/chat/completions` | Core chat completion proxy (streaming + non-streaming) | 2-3 days |
| `GET /v1/models` | Model enumeration for clients | 2 hours |
| `POST /v1/embeddings` | Embedding proxy for RAG pipelines | 1 day |
| `GET /health`, `/health/readiness`, `/health/liveliness` | K8s/Docker health probes | 2 hours |
| `GET /metrics` | Prometheus metrics endpoint | 1 day |

### Endpoints CommandClaw Does Not Need

| Endpoint | Why Skip |
|---|---|
| `POST /v1/messages` | Anthropic-native format; commandclaw uses OpenAI-compat via LangChain |
| `POST /v1/responses` | OpenAI Responses API; not used by LangGraph |
| `POST /v1/completions` | Legacy text completion; superseded by chat |
| `/audio/transcriptions`, `/audio/speech`, `/realtime` | Audio not in scope |
| `/images/generations`, `/images/edits`, `/videos` | Image/video gen not in scope |
| `/files`, `/vector_stores`, `/containers` | File/vector management done elsewhere |
| `/fine_tuning`, `/batches` | Fine-tuning/batch done via provider UIs |
| `/rag/ingest`, `/rag/query` | RAG handled by LangGraph retrieval nodes |
| `/evals`, `/moderations` | Evaluation done via Langfuse/custom |
| `/ocr`, `/rerank`, `/search` | Specialized endpoints; not core |
| `/assistants` | Deprecated (shutting down Aug 2026) |
| `/a2a` | A2A agent protocol; commandclaw has its own agent routing |
| `/mcp` | MCP already handled by commandclaw-mcp |
| `/converse`, `/invoke` | Bedrock-specific pass-through |
| `/generateContent` | Google-specific pass-through |
| `Pass-through Endpoints` (15+ providers) | Native SDK pass-through; unnecessary with provider adapters |
| `/skills` | Anthropic-specific |

**Verdict:** LiteLLM exposes ~40 endpoint groups. CommandClaw needs 5. The remaining 35 are specialized capabilities that CommandClaw either handles elsewhere or does not need. This alone eliminates ~85% of LiteLLM's API surface from scope.

---

## 2. Provider Support

LiteLLM supports 100+ providers and 2,500+ models [4][37]:

### Providers CommandClaw Needs (Current + Near-Term)

| Provider | Priority | Adapter Effort |
|---|---|---|
| OpenAI (GPT-4o, o3, etc.) | P0 — primary | 1 day (OpenAI-compatible = baseline) |
| Anthropic (Claude 4.x) | P0 — primary | 1-2 days (different message format) |
| Google Vertex AI / Gemini | P1 — secondary | 1-2 days |
| AWS Bedrock | P1 — secondary | 1-2 days (SigV4 auth) |
| Ollama (local) | P1 — dev/testing | 2 hours (OpenAI-compatible) |
| Groq | P2 — optional | 2 hours (OpenAI-compatible) |
| DeepSeek | P2 — optional | 2 hours (OpenAI-compatible) |

### Providers CommandClaw Can Skip

The remaining 93+ providers (AI21, Aleph Alpha, Cerebras, Clarifai, Cohere, DataRobot, Databricks, ElevenLabs, Fireworks, HuggingFace, Mistral, Replicate, RunwayML, Stability AI, Together AI, vLLM, xAI, etc.) are not needed at current scale. Any OpenAI-compatible provider works with zero adapter effort via the baseline adapter.

**Provider adapter architecture** (from LiteLLM's own pattern [4]):
- Each provider is a `BaseConfig` subclass with 4 methods: `validate_environment()`, `get_complete_url()`, `transform_request()`, `transform_response()`
- OpenAI-compatible providers need zero custom code — they use the baseline adapter
- Only providers with non-OpenAI wire formats need custom adapters (Anthropic, Bedrock, Vertex)

**Build effort for all P0+P1 providers: ~5 days.** Each additional OpenAI-compatible provider: 2 hours.

---

## 3. Routing and Load Balancing

LiteLLM's Router class implements 6 routing strategies [8][10]:

| Strategy | What It Does | CommandClaw Need | Build Effort |
|---|---|---|---|
| `simple-shuffle` | Random with RPM/TPM weights | **Yes** — recommended default | 1 day |
| `least-busy` | Fewest concurrent requests | **Yes** — good for spikes | 4 hours |
| `latency-based-routing` | Lowest recent response time | **Defer** — optimize later | 1 day |
| `usage-based-routing` | Lowest TPM usage | **Skip** — officially "not recommended" | — |
| `cost-based-routing` | Cheapest available | **Defer** | 4 hours |
| Custom plugin | User-defined logic | **Defer** | 1 day |

Additional routing features:
- `order` — deployment priority tiers: **Yes**, simple integer sort
- `weight` — weighted selection frequency: **Yes**, built into shuffle
- `max_parallel_requests` — per-deployment concurrency cap: **Yes**, semaphore
- Model aliasing (`model_group_alias`): **Yes**, dict lookup
- Traffic mirroring (A/B testing): **Defer**
- Pre-call checks (context window validation, EU-region filtering): **Defer**
- Encrypted content affinity: **Skip** — niche enterprise

**Build effort for core routing (shuffle + least-busy + order + weights): ~2 days.**

---

## 4. Reliability — Fallbacks, Retries, Cooldowns

LiteLLM implements a sophisticated reliability stack [9]:

| Feature | What It Does | CommandClaw Need | Build Effort |
|---|---|---|---|
| Standard fallbacks | Fallback chain on any error | **Yes** | 4 hours |
| Context window fallbacks | Auto-route to larger model on overflow | **Yes** | 2 hours |
| Content policy fallbacks | Route to different provider on content block | **Defer** | 2 hours |
| Default fallbacks | Global fallback when all groups fail | **Yes** | 1 hour |
| `num_retries` | Configurable per-deployment | **Yes** | 2 hours |
| Exponential backoff with jitter | Rate limit retry handling | **Yes** | 2 hours |
| `Retry-After` header parsing | Provider-specified wait | **Yes** | 1 hour |
| Cooldown system (`allowed_fails`, `cooldown_time`) | Pause failing deployments | **Yes** | 4 hours |
| `RetryPolicy` class | Per-exception retry counts | **Defer** | 2 hours |
| `AllowedFailsPolicy` | Per-exception failure thresholds | **Defer** | 2 hours |
| Mock testing fallbacks | Simulate failures for testing | **Defer** | 1 hour |
| Per-request `disable_fallbacks` | Client override | **Defer** | 30 min |

**Build effort for core reliability (fallbacks + retries + cooldowns): ~2 days.**

---

## 5. Caching

LiteLLM supports 9 cache backends [11]:

| Backend | CommandClaw Need | Build Effort |
|---|---|---|
| Redis cache (exact match) | **Yes** — primary | 1 day |
| In-memory cache | **Yes** — dev/testing | 4 hours |
| Redis Cluster | **Defer** | 2 hours (config change) |
| Redis Sentinel | **Defer** | 2 hours |
| Qdrant semantic cache | **Defer** | 2 days |
| Redis semantic cache | **Defer** | 1 day |
| S3 bucket cache | **Skip** | — |
| GCS bucket cache | **Skip** | — |
| Disk cache | **Skip** | — |

Per-request cache controls: `ttl`, `s-maxage`, `no-cache`, `no-store`, `namespace`, `use-cache` — **Yes**, straightforward HTTP header parsing.

Cache debugging: `GET /cache/ping`, `DELETE /cache/delete`, response headers (`x-litellm-cache-key`) — **Yes**, trivial.

**Build effort for Redis exact cache + in-memory + per-request controls: ~1.5 days.**

---

## 6. Authentication and Virtual Keys

LiteLLM's virtual key system is extensive [15][22]:

### Core Features CommandClaw Needs

| Feature | Build Effort |
|---|---|
| Virtual key generation (`POST /key/generate`) | 4 hours |
| Key validation middleware | 2 hours |
| Per-key model allowlist | 2 hours |
| Per-key `max_budget`, `budget_duration` | 4 hours |
| Per-key `tpm_limit`, `rpm_limit` | 2 hours (reuse rate limiter) |
| Key block/unblock | 1 hour |
| Key info endpoint | 1 hour |

### Features CommandClaw Can Skip or Defer

| Feature | Why |
|---|---|
| Key rotation with grace period | Defer — commandclaw-mcp already has rotation |
| `upperbound_key_generate_params` | Defer — admin constraint |
| `default_key_generate_params` | Defer — convenience |
| `key_generation_settings` (role-based) | Defer — small team |
| Custom key generation function | Skip — overengineered |
| JWT/OIDC authentication (15+ config params) | **Defer** — commandclaw uses API keys; SSO comes later |
| Kubernetes ServiceAccount auth | Skip — niche |
| OIDC UserInfo endpoint | Skip |

**Build effort for core virtual keys: ~2 days.** JWT/OIDC: additional 3-5 days when needed.

---

## 7. Multi-Tenancy — Orgs, Teams, Users

LiteLLM's four-level hierarchy [17][18]:

| Level | CommandClaw Need | Build Effort |
|---|---|---|
| Virtual Keys | **Yes** (see above) | (included above) |
| Users | **Yes** — per-agent tracking | 1 day |
| Teams | **Defer** — single team initially | 1 day when needed |
| Organizations | **Skip** — enterprise feature | — |

Per-level budget enforcement (hierarchical): **Yes** for keys and users, **defer** for teams/orgs.

RBAC roles (`proxy_admin`, `internal_user`, `team_admin`, etc.): **Defer** — commandclaw-mcp already has Cerbos RBAC. Reuse that.

Self-serve UI, invitation system, SSO auto-provisioning: **Skip** — admin manages keys directly.

**Build effort for users + key-level budgets: ~1 day (on top of virtual keys).**

---

## 8. Cost Tracking and Budgets

LiteLLM's cost tracking surface [16][18]:

### Core Features CommandClaw Needs

| Feature | Build Effort |
|---|---|
| Per-request cost calculation (`response_cost`) | 4 hours |
| Token counting (tiktoken + fallback) | 2 hours |
| Per-key spend accumulation | 2 hours (Redis counter) |
| Per-user spend tracking | 1 hour |
| Budget enforcement (block on exceed) | 2 hours |
| `x-litellm-response-cost` response header | 30 min |
| Cost pricing table (per-model input/output rates) | 2 hours (static YAML) |

### Features CommandClaw Can Skip or Defer

| Feature | Why |
|---|---|
| `GET /global/spend/report` with grouping | Defer — query Langfuse instead |
| `GET /user/daily/activity` | Defer — use Grafana dashboards |
| `GET /spend/logs` | Defer — Langfuse has full logs |
| `POST /global/spend/reset` | Defer |
| Custom spend tags (`metadata.tags`) | Defer |
| Spend logs metadata | Defer |
| Model-specific budgets (enterprise) | Skip |
| Agent-specific budgets with iteration caps | Defer |
| Customer/end-user budget management | Skip |
| Pricing sync from GitHub | Defer — manual updates fine initially |

**Build effort for core cost tracking: ~1.5 days.**

---

## 9. Rate Limiting

LiteLLM's rate limiting [12][18]:

| Feature | CommandClaw Need | Build Effort |
|---|---|---|
| Per-key RPM (requests/minute) | **Yes** | 2 hours (Redis sliding window) |
| Per-key TPM (tokens/minute) | **Yes** | 2 hours |
| Per-model RPM/TPM | **Defer** | 2 hours |
| Per-team rate limits | **Defer** | 1 hour |
| Budget tiers (enterprise) | **Skip** | — |
| `token_rate_limit_type` (input/output/total) | **Defer** | 1 hour |
| Rate limit response headers | **Yes** | 1 hour |
| Multi-instance sync via Redis | **Yes** | (included — Redis-backed) |

**Build effort for per-key RPM/TPM with Redis: ~0.5 days.**

---

## 10. Observability

LiteLLM's observability surface is massive [24][25][26][27][29][30]:

### Prometheus Metrics (40+ metrics)

CommandClaw needs a subset:

| Metric | Need |
|---|---|
| `litellm_spend_metric` (counter by key/team/model) | **Yes** |
| `litellm_input_tokens_metric`, `litellm_output_tokens_metric` | **Yes** |
| `litellm_request_total_latency_metric` (histogram) | **Yes** |
| `litellm_llm_api_latency_metric` (provider-only latency) | **Yes** |
| `litellm_llm_api_time_to_first_token_metric` | **Yes** |
| `litellm_proxy_total_requests_metric` | **Yes** |
| `litellm_proxy_failed_requests_metric` | **Yes** |
| `litellm_deployment_state` (health gauge) | **Yes** |
| Budget remaining gauges | **Defer** |
| Rate limit remaining gauges | **Defer** |
| Redis/system health metrics | **Defer** |
| Callback delivery monitoring | **Defer** |

Build effort for ~10 core Prometheus metrics: **1 day** (using `prometheus_client`).

### Logging Destinations (25+)

CommandClaw needs:
- **Langfuse** — already in use, `@observe` decorator or callback
- **Prometheus** — already in commandclaw-observe
- **Structured JSON logs** — standard Python logging

The remaining 22+ destinations (S3, SQS, Azure Blob, DynamoDB, GCS, PubSub, Datadog, Sentry, Arize, Lunary, etc.) are not needed.

### Alerting (4 channels, 15+ alert types)

CommandClaw needs:
- Slack webhook for budget alerts and deployment outages: **1 day**
- Everything else (Discord, Teams, digest mode, regional outage detection): **Defer**

### Custom Callbacks (6 hook points)

CommandClaw needs:
- `async_log_success_event` and `async_log_failure_event`: **Yes**, for Langfuse
- The remaining hooks (`log_pre_api_call`, `log_post_api_call`, etc.): **Defer**

Build effort for callback system: **4 hours** (simple event emitter pattern).

**Total observability build effort: ~3 days.**

---

## 11. Guardrails

LiteLLM supports 8 guardrail providers with pre/post/during-call modes [28]:

| Provider | CommandClaw Need |
|---|---|
| Presidio (PII detection/redaction) | **Defer** — add when compliance requires |
| Bedrock Guardrails | **Defer** |
| Lakera (prompt injection) | **Defer** |
| Aporia | Skip |
| guardrails_ai | Skip |
| Azure Text Moderations | Skip |
| AIM | Skip |
| Generic guardrail API | **Defer** — useful as extension point |

Guardrail architecture (pre_call / post_call / during_call modes, per-key assignment, team-level controls): well-designed but entirely deferrable.

**Build effort when needed: ~2-3 days for Presidio PII + generic API hook.**

---

## 12. Health Checks

LiteLLM's health system [31]:

| Feature | CommandClaw Need | Build Effort |
|---|---|---|
| `GET /health/liveliness` | **Yes** | 30 min |
| `GET /health/readiness` (DB check) | **Yes** | 30 min |
| `GET /health` (model health via API calls) | **Defer** | 1 day |
| Background health checks | **Defer** | 4 hours |
| Cross-pod health sync via Redis | **Skip** | — |

**Build effort for basic health: ~1 hour.**

---

## 13. Deployment and Infrastructure

LiteLLM's deployment surface [6][7]:

| Feature | CommandClaw Need |
|---|---|
| Docker deployment | **Yes** — standard Dockerfile |
| Docker Compose with Postgres | **Yes** — add to existing stack |
| Kubernetes (ConfigMap, Secrets, HPA) | **Defer** |
| Helm chart (BETA) | **Skip** |
| Terraform provider | **Skip** |
| Cloud-specific (Cloud Run, Railway, Render) | **Skip** |
| AWS CloudFormation stack | **Skip** |
| Cosign image verification | **Skip** |
| Non-root image | **Defer** |
| HTTP/2 via Hypercorn | **Skip** |
| Control plane / data plane split | **Skip** — enterprise |
| Read-only filesystem | **Defer** |

**Build effort: ~0.5 days** (Dockerfile + docker-compose service entry).

---

## 14. Admin UI

LiteLLM ships a web dashboard for key management, model management, spend tracking, and AI Hub [32].

**CommandClaw need: Skip entirely.** Admin manages keys via CLI/API. Grafana handles dashboards. The UI is a significant engineering effort (~2-4 weeks) with no value for a small team.

---

## 15. Protocol Support (A2A, MCP)

LiteLLM supports A2A agent protocol and MCP gateway [35][36]:

- **A2A**: Agent-to-agent protocol with JSON-RPC 2.0, iteration budgets, streaming. **Skip** — commandclaw has its own agent routing.
- **MCP**: Tool listing, calling, prompts, resources, 6 auth methods, 3 transports. **Skip** — commandclaw-mcp already handles this.

---

## Scope Estimation Summary

### What CommandClaw Needs (Build Scope)

| Domain | Features Needed | Est. Build Days |
|---|---|---|
| **API Surface** | `/chat/completions`, `/models`, `/embeddings`, health, metrics | 3 |
| **Provider Adapters** | OpenAI, Anthropic, Vertex, Bedrock, Ollama | 5 |
| **Routing** | Shuffle, least-busy, ordered priority, weights | 2 |
| **Reliability** | Fallbacks, retries, exponential backoff, cooldowns | 2 |
| **Caching** | Redis exact cache, in-memory, per-request controls | 1.5 |
| **Virtual Keys** | Key generation, validation, model allowlists | 2 |
| **Budgets & Cost** | Per-key/user budgets, token cost calculation | 1.5 |
| **Rate Limiting** | Per-key RPM/TPM via Redis | 0.5 |
| **Observability** | ~10 Prometheus metrics, Langfuse callbacks, Slack alerts | 3 |
| **Health Checks** | Liveness, readiness | 0.5 |
| **Deployment** | Dockerfile, docker-compose entry | 0.5 |
| **Config** | YAML config loader, env var substitution | 1 |
| | | |
| **Total** | | **~22 days (4-5 weeks, 1 engineer)** |

### What CommandClaw Can Skip (~85% of LiteLLM)

| Domain | Why Skip | LiteLLM Effort Saved |
|---|---|---|
| 35 endpoint groups (audio, images, video, files, RAG, evals, assistants, etc.) | Not needed; handled elsewhere or out of scope | Months |
| 93+ provider adapters | Only need 5-7 providers; OpenAI-compat covers most | Months |
| JWT/OIDC/SSO (15+ config params) | API keys sufficient; commandclaw-mcp has auth | 1-2 weeks |
| Multi-tenant hierarchy (orgs, teams) | Single team initially | 2-3 weeks |
| 8 guardrail providers | Compliance not yet required | 2-3 weeks |
| 9 cache backends (semantic, S3, GCS, Qdrant, etc.) | Redis exact cache sufficient | 2-3 weeks |
| 25+ logging destinations | Langfuse + Prometheus sufficient | 3-4 weeks |
| Admin UI | CLI/API + Grafana sufficient | 3-4 weeks |
| A2A gateway | Own agent routing | 1-2 weeks |
| MCP gateway | commandclaw-mcp handles this | Already built |
| Enterprise features (SSO >5 users, audit logs, model budgets) | Not needed | Weeks |
| Cloud-specific deployment (ECS, EKS, CloudFormation, Cloud Run) | Docker Compose sufficient | 1-2 weeks |
| Control plane / data plane split | Not multi-region | 1-2 weeks |
| Advanced routing (latency-based, cost-based, custom plugin) | Optimize later | 1 week |

### What CommandClaw Should Defer (Add When Needed)

| Feature | Trigger to Add |
|---|---|
| JWT/OIDC auth | When SSO is needed |
| Team/org hierarchy | When >1 team uses the platform |
| Guardrails (PII, injection) | When compliance/enterprise requires |
| Semantic caching | When exact cache hit rate is insufficient |
| Latency-based routing | When running 3+ deployments of same model |
| Cost-based routing | When cost optimization becomes a priority |
| Background health checks | When running >5 provider endpoints |
| Traffic mirroring | When evaluating new models in production |
| Admin UI | When team size warrants self-serve |

---

## Revised Build Recommendation

The previous whitepaper recommended **Option C: hybrid with LiteLLM SDK as a library**. Given the vulnerability concern and this feature analysis, the recommendation shifts to:

### Option D: Build a Standalone Custom Gateway (No LiteLLM Dependency)

**Rationale:**
1. CommandClaw needs ~15% of LiteLLM's features — the vast majority is irrelevant scope.
2. LiteLLM's Python package imports 100+ provider modules, adding cold-start overhead, dependency surface, and vulnerability exposure even when using only the SDK.
3. The core patterns (provider adapters, routing, fallbacks, caching, virtual keys, cost tracking) are well-documented and straightforward to implement.
4. CommandClaw already has FastAPI, Redis, Langfuse, Prometheus, and virtual key patterns in commandclaw-mcp — the building blocks exist.
5. A custom gateway with 5-7 provider adapters is ~2,000-3,000 lines of Python — maintainable by one engineer.

**Architecture:**

```
commandclaw-gateway/
  main.py              # FastAPI app, routes
  config.py            # YAML config loader
  auth.py              # Virtual key validation, budget check
  router.py            # Routing strategies (shuffle, least-busy, fallbacks)
  providers/
    base.py            # BaseLLMProvider ABC
    openai.py          # OpenAI adapter (baseline)
    anthropic.py       # Anthropic adapter
    vertex.py          # Vertex AI adapter
    bedrock.py         # AWS Bedrock adapter
  middleware/
    rate_limiter.py    # Redis-backed RPM/TPM
    cost_tracker.py    # Token counting + spend accumulation
    cache.py           # Redis exact cache
  observability/
    metrics.py         # Prometheus counters/histograms
    callbacks.py       # Langfuse + Slack alerting
  models.py            # Pydantic request/response models
```

**Estimated effort: 4-5 weeks for one engineer.** This produces a gateway that:
- Handles 100% of CommandClaw's current LLM traffic needs
- Has zero dependency on LiteLLM (no vulnerability exposure)
- Reuses commandclaw-mcp's Redis, auth patterns, and observability stack
- Integrates natively with commandclaw-observe (Prometheus + Grafana)
- Provides a clean migration path to add features as needed

**What you lose vs. LiteLLM:** Automatic pricing updates, community-maintained provider adapters, admin UI, 100+ pre-built provider integrations. All of these are "nice to have" but not "need to have" for CommandClaw's current scale.

---

## Conclusion

LiteLLM is a sprawling platform with ~400+ features across 14 functional domains. Its documentation reveals a product that has grown from a simple LLM proxy into a full AI platform with agent gateways (A2A), tool servers (MCP), file management, RAG pipelines, fine-tuning, evaluations, and more. For CommandClaw, this represents significant unnecessary complexity and dependency surface.

The feature inventory shows CommandClaw needs approximately 60 discrete features concentrated in 4 domains: provider proxying, routing/reliability, credential management, and observability. These features are well-understood, well-documented, and straightforward to implement on top of CommandClaw's existing infrastructure.

Building a standalone gateway eliminates the LiteLLM vulnerability concern entirely, reduces the dependency footprint to standard Python libraries (FastAPI, httpx, tiktoken, prometheus_client, redis), and produces a gateway that is architecturally coherent with the rest of the CommandClaw ecosystem.

---

## References

See [litellm-feature-inventory-references.md](litellm-feature-inventory-references.md) for the full bibliography (37 sources).
