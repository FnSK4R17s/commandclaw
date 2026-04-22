# commandclaw-observe — the self-hosted observability stack

> Langfuse v3 tracing + Prometheus metrics + Grafana dashboards. One compose, zero config. For teams that need data sovereignty.

## Why it exists

Every other service in the ecosystem emits telemetry: [runtime](commandclaw.md) sends Langfuse traces, [MCP gateway](commandclaw-mcp.md) exports OTLP + Prometheus, [LLM gateway](commandclaw-gateway.md) exports Prometheus + Langfuse. Those signals need a home.

For most users that home is the cloud — hosted Langfuse, Grafana Cloud, or similar. Works great, zero ops burden. `commandclaw-observe` is the **alternative for teams that can't send LLM traffic off-network** (compliance, privacy, air-gapped environments). It packages the backends as a single Docker Compose so self-hosting is a one-command affair instead of a four-week evaluation.

The design goal is **parity with hosted**: same Langfuse UI, same Grafana UI, same metrics, no proprietary agents or collectors between the app and the backend. Point the `COMMANDCLAW_LANGFUSE_*` env vars at `localhost:3000` and traces start flowing immediately.

## What it does

| Capability | Detail |
|---|---|
| **LLM tracing** | Langfuse v3 — multimodal, vision, tool calls, nested spans, token cost. |
| **Metrics storage** | Prometheus v2.53, scraping the MCP gateway and LLM gateway. |
| **Dashboards** | Grafana 11.1 with provisioned dashboards for MCP gateway metrics. |
| **Object storage** | MinIO (S3-compatible) for Langfuse media assets. |
| **OLTP + OLAP for Langfuse** | Postgres 17 for transactional state; ClickHouse for analytics. |
| **Queues + cache** | Redis 7 for Langfuse worker queues. |

## Tech stack and why

| Choice | Reason |
|---|---|
| **Docker Compose** | Single command to bring up ~8 services. No Kubernetes requirement; no Helm chart tax. |
| **Langfuse v3** | Best-in-class open-source LLM observability. Supports multimodal traces, cost tracking, and evaluation. Matches the `langfuse` SDK the rest of the stack uses. |
| **Langfuse Worker** | Async event processor; decouples UI latency from ingest throughput. |
| **Postgres 17 (alpine)** | OLTP store for Langfuse metadata (projects, users, trace headers). Reliable, boring, minimal image. |
| **ClickHouse** | OLAP store for Langfuse trace analytics. Column-oriented, blazing fast aggregation, the reason Langfuse scales. |
| **Redis 7** | Queue + cache for the Langfuse worker. |
| **MinIO (Chainguard image)** | S3-compatible object store for media (screenshots, attachments). Chainguard image keeps CVE noise down. |
| **Prometheus 2.53** | Pull-based metrics, scrapes `/metrics` on MCP + LLM gateways. Well-understood, native to the Prometheus client libs the other services use. |
| **Grafana 11.1** | Dashboards and alerting. Provisioned configs checked into the repo; upgrades are diffable. |
| **No Jaeger/Tempo** | Langfuse covers LLM-centric tracing. Separate distributed-trace backend would be redundant for this ecosystem; add OTEL collector + Tempo later if needed. |

## Internal architecture

```
commandclaw-observe/
├── docker-compose.yml     ← the whole stack
├── prometheus/
│   └── prometheus.yml     ← scrape configs for the gateways
├── grafana/
│   ├── provisioning/      ← datasources + dashboards (declarative)
│   └── dashboards/        ← JSON dashboards (diffable in git)
└── README.md
```

### Service map

```
 ┌────────────────────┐      ┌────────────────────┐
 │  commandclaw       │      │  commandclaw-mcp   │
 │  (runtime, traces) │      │  (metrics /metrics)│
 └─────────┬──────────┘      └──────────┬─────────┘
           │                            │
           │ Langfuse SDK               │ Prometheus scrape
           ▼                            ▼
 ┌────────────────────┐      ┌────────────────────┐
 │  Langfuse :3000    │◄────►│  Prometheus :9092  │
 │  (UI + API)        │      │  (metrics store)   │
 └─┬──────────────────┘      └──────────┬─────────┘
   │                                    │
   │ async events                       │
   ▼                                    ▼
 ┌────────────────────┐        ┌────────────────────┐
 │ Langfuse Worker    │        │  Grafana :3001     │
 │ (:3030 internal)   │        │  (dashboards)      │
 └─┬────┬─────┬──────┘        └────────────────────┘
   │    │     │
   ▼    ▼     ▼
 ┌────┐┌────┐┌──────┐┌──────┐
 │ PG ││Redis││ CH  ││MinIO │
 └────┘└────┘└──────┘└──────┘
```

### Port map

| Service | Port | Purpose |
|---|---|---|
| Langfuse | 3000 | Web UI + API |
| Langfuse Worker | 3030 (internal) | Async events |
| Grafana | 3001 | Dashboards |
| Prometheus | 9092 | Metrics scrape |
| MinIO | 9091 | Object store UI |
| ClickHouse | internal | OLAP |
| Postgres | internal | OLTP |
| Redis | internal | Queue/cache |

## External interfaces

| Interface | Direction | Used for |
|---|---|---|
| **Langfuse HTTP/SDK** | any app → `:3000` | Trace ingest (runtime, gateway). |
| **Prometheus `/metrics` scrape** | Prometheus → gateways | Pull metrics every N seconds. |
| **Browser HTTP** | user → `:3000`, `:3001`, `:9091` | Human UIs. |
| **S3 API** | Langfuse → MinIO | Media upload/download. |

## Deployment shape

```bash
gh repo clone FnSK4R17s/commandclaw-observe
cd commandclaw-observe
docker compose up -d
open http://localhost:3000   # Langfuse
open http://localhost:3001   # Grafana
```

Then in the runtime's `.env`:

```
COMMANDCLAW_LANGFUSE_PUBLIC_KEY=pk-lf-local
COMMANDCLAW_LANGFUSE_SECRET_KEY=sk-lf-local
COMMANDCLAW_LANGFUSE_HOST=http://localhost:3000
```

## Do you need this?

**Most users don't.** Hosted [Langfuse Cloud](https://langfuse.com) and [Grafana Cloud](https://grafana.com/products/cloud/) work great and require no infrastructure. Self-host if:

- LLM traffic can't leave the network (compliance, privacy, air-gapped).
- Full control over trace retention and data lifecycle is required.
- Enterprise deployment with strict data-sovereignty requirements.

## Why this stack over alternatives

| Alternative | Why we didn't |
|---|---|
| **Elastic/Datadog/New Relic** | LLM-specific tracing is bolt-on or absent. Langfuse was built for this. |
| **OpenTelemetry Collector + Tempo + Loki + Grafana** | Fine general stack; lacks LLM-native features (token cost, prompt diffs, eval) without custom work. Adding Langfuse anyway on top duplicates. |
| **Prometheus alone** | No traces. |
| **Langfuse alone** | No metrics/dashboards for infra (Redis, gateway latency). |

The combo gives Langfuse for LLM-specific signal, Prometheus for infra signal, Grafana for the unified view — all open-source, all self-hostable, all portable to the cloud if priorities change.

## Key files

- [docker-compose.yml](../../../commandclaw-observe/docker-compose.yml) — the whole stack
- [prometheus/prometheus.yml](../../../commandclaw-observe/prometheus/prometheus.yml) — scrape config
- [grafana/](../../../commandclaw-observe/grafana) — provisioned dashboards
