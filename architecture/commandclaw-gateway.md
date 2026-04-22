# commandclaw-gateway — the LLM routing layer

> One interface, every LLM. Virtual keys, budgets, rate limits, multi-provider fallback. No LiteLLM dependency.

## Why it exists

Running agents in production means running many of them, across many model providers, with many humans watching the bill. The cross-cutting concerns — credential isolation, budget enforcement, rate limiting, cost tracking, caching, guardrails, provider failover — belong in exactly one place, not duplicated in every agent.

Off-the-shelf options exist (LiteLLM, Portkey, Helicone). `commandclaw-gateway` is a first-party alternative built to match the rest of the ecosystem: same auth model (virtual keys ≈ phantom tokens), same observability stack (Langfuse + Prometheus), same deployment story (Docker Compose), same Python idioms, no coupling to a vendor that could change terms.

It serves both OpenAI (`/v1/chat/completions`) and Anthropic (`/v1/messages`) wire formats from a single service, so agents can be written against either SDK without knowing about the gateway.

## What it does

Status on every row below: **implemented**.

| Capability | Detail |
|---|---|
| **Dual-format API** | OpenAI `/v1/chat/completions` + Anthropic `/v1/messages`, both streaming and non-streaming. |
| **Provider adapters** | OpenAI, Anthropic, Vertex AI, Bedrock, Ollama, plus OpenAI-compat baseline for Groq, DeepSeek, etc. |
| **Virtual keys** | Per-agent keys with budgets, rate limits, model allowlists, team/org membership. Rotate (grace period), block/unblock, delete. |
| **Routing** | Filter pipeline (cooldown → region → context window → upstream awareness) feeding a strategy (shuffle, least-busy, latency, cost, custom plugin). |
| **Fallbacks** | Standard, context-window-overflow, content-policy. Per-model fallback chains. |
| **Retries + cooldowns** | Exponential backoff with jitter, `Retry-After` compliance, per-exception retry/cooldown policies. |
| **Cost tracking** | tiktoken counting, YAML pricing table, hierarchical spend (org > team > user > key), spend tags, spend logs. |
| **Rate limiting** | Redis sliding windows + token bucket. Multi-dimensional: key / key-per-model / user / team / org / model-global. RPM + TPM + daily/monthly quotas. |
| **Caching** | Redis exact-match + in-memory, streaming assembly, per-model TTL, multi-tenant `cache_scope`, per-call-type enforcement. |
| **Guardrails** | Presidio + builtin PII detection/redaction, prompt-injection detection, generic guardrail API, per-key assignment, Langfuse-traced execution. |
| **Auth** | Virtual keys + JWT/OIDC (JWKS + symmetric). Pluggable middleware. |
| **RBAC** | `proxy_admin`, `team_admin`, `internal_user`. Key-generation bounds. |
| **Teams + Orgs** | Budgets, rate limits, model allowlists, guardrail policies, region constraints. |
| **Audit trail** | Immutable append-only log of key/team/org ops, queryable. |
| **Batch + Responses API** | `POST /v1/batches`, `POST /v1/responses` (translates to/from chat completions). |
| **Observability** | ~20 Prometheus metrics (all labeled team/org/key/model), Langfuse tracing, Slack alerts, callback monitoring. |
| **Spend reporting** | `GET /global/spend/report`, `/global/spend/daily`, `POST /global/spend/reset`. |

## Tech stack and why

| Choice | Reason |
|---|---|
| **Python 3.11+** | Ecosystem fit — every provider SDK is first-class in Python. `pyproject.toml` keeps min-version honest. |
| **FastAPI + uvicorn** | Async streaming, automatic OpenAPI, easy middleware stack for auth / rate limit / cost / guardrail. |
| **httpx** | Async HTTP with HTTP/2. Single client pool across provider adapters. |
| **pydantic 2.7+** | Strict request/response schemas for both OpenAI and Anthropic formats. |
| **Redis** | Rate limits, cache, key metadata, spend counters, cooldowns — every bit of shared state. One store, trivial HA story. |
| **tiktoken** | Accurate token counting for OpenAI-family models; underpins cost tracking and rate limits. |
| **cryptography** | Secret encryption at rest. |
| **boto3** | Bedrock provider. |
| **google-auth** | Vertex AI provider. |
| **python-ulid** | Monotonic-ish identifiers for keys, spends, audit events. |
| **sse-starlette** | Server-sent events for streamed completions. |
| **prometheus-client** | Native metric export at `/metrics`. |
| **Langfuse SDK (v3)** | First-class trace of every LLM call, with guardrail execution as sub-spans. |
| **pytest + fakeredis** | Tests hit a fake Redis; no infrastructure required. |
| **No LiteLLM** | Deliberate. Owning the routing/fallback/cost logic means no surprise upgrades and no feature lag. |

## Internal architecture

```
commandclaw-gateway/
├── main.py               FastAPI app factory, router registration
├── config.py             Pydantic settings, YAML loader
├── config.yaml           Deployment config (deployments, models, routing)
├── pricing.yaml          Per-model token prices
├── routes/               /v1/chat/completions, /v1/messages, /v1/embeddings,
│                         /v1/batches, /v1/responses, /global/spend/*, admin
├── middleware/           Auth, rate limit, budget, cache, guardrails, observability
├── auth/                 Virtual key issue/rotate/validate, JWT/OIDC verify, RBAC
├── routing/              Filter pipeline + strategies + fallback engine
├── providers/            Per-provider adapter (OpenAI, Anthropic, Vertex, Bedrock, Ollama)
├── schemas/              OpenAI + Anthropic wire-format Pydantic models
├── observability/        Prometheus metrics, Langfuse wrapper, Slack alerts
└── infra/                Shared clients (Redis, httpx), startup/shutdown
```

### Request pipeline

```
POST /v1/chat/completions  (OpenAI format)
 or  /v1/messages           (Anthropic format)
       │
       ▼
 Auth middleware            → virtual key or JWT → resolve key / team / org / user
       ▼
 RBAC                        → role checks, key-generation bounds
       ▼
 Rate limiter                → sliding window + token bucket across all dimensions
       ▼
 Budget check                → hierarchical: org > team > user > key
       ▼
 Cache lookup                → Redis / in-memory, respecting cache_scope
       ▼
 Guardrail chain (pre)       → PII redaction, prompt injection, custom
       ▼
 Router
   ├─ Filter pipeline        → cooldown, region, context window, upstream
   └─ Strategy               → shuffle / least-busy / latency / cost / plugin
       ▼
 Provider adapter call       → httpx to OpenAI / Anthropic / Vertex / Bedrock / Ollama
   └─ Reliability engine     → retries with jitter, cooldowns on failure,
                                fallback chain on overflow/policy failures
       ▼
 Guardrail chain (post)      → output redaction, policy enforcement
       ▼
 Cost tracker                → tiktoken count, pricing table, spend accumulation,
                                spend logs with tags
       ▼
 Cache write + response      → stream SSE or send JSON, write Langfuse trace
```

### Streaming

Streamed responses are assembled during the call (for caching and cost) and re-emitted as SSE to the client — so caching and token counting work regardless of stream mode.

## External interfaces

| Interface | Direction | Used for |
|---|---|---|
| **HTTP (OpenAI format)** | [runtime](commandclaw.md), any OpenAI SDK → gateway | LLM calls. |
| **HTTP (Anthropic format)** | any Anthropic SDK → gateway | LLM calls. |
| **HTTPS** | gateway → providers | OpenAI, Anthropic, Vertex, Bedrock, Ollama. |
| **Redis** | gateway ↔ Redis | Cache, rate limits, spend, keys, teams, orgs. |
| **Langfuse SDK** | gateway → [commandclaw-observe](commandclaw-observe.md) or Langfuse Cloud | Traces, guardrail execution audit. |
| **Prometheus** | Prometheus → `/metrics` | Scrape endpoint (~20 metrics with team/org/key/model labels). |
| **Slack Webhook** | gateway → Slack | Alert channel for budget breaches, fallback storms, deployment health. |

## Deployment shape

```yaml
# docker-compose.yml
services:
  commandclaw-gateway:     # FastAPI, port 4000
  redis:                   # state store
  # optional: prometheus, langfuse — reuse commandclaw-observe if self-hosting
```

Config split:
- [config.yaml](../../../commandclaw-gateway/config.yaml) — deployments, models, routing strategy.
- [pricing.yaml](../../../commandclaw-gateway/pricing.yaml) — per-model token prices.
- Secrets in env; never in repo.

## Why a first-party gateway over LiteLLM or Portkey

| Alternative | Why we didn't |
|---|---|
| **LiteLLM** | Feature-rich, but a heavy Python dependency with its own opinions about auth and storage. We want the gateway's identity, audit, and telemetry model to be *ours*. |
| **Portkey / Helicone** | SaaS. Fine for small teams. Fails the "data never leaves our network" requirement we share with [commandclaw-observe](commandclaw-observe.md). |
| **Run without a gateway** | Agents end up holding provider keys. Budget/rate-limit enforcement lives in N places or nowhere. |

Running our own means: same auth primitives as the MCP gateway, same observability, same deployment shape, no surprise breaking changes from upstream.

## Key files

- [main.py](../../../commandclaw-gateway/main.py) — FastAPI app
- [config.yaml](../../../commandclaw-gateway/config.yaml) — deployments + routing
- [routing/](../../../commandclaw-gateway/routing) — filters + strategies + fallback engine
- [providers/](../../../commandclaw-gateway/providers) — per-provider adapters
- [auth/](../../../commandclaw-gateway/auth) — virtual keys, JWT, RBAC
