# LiteLLM Feature Inventory — Research Notes

## Source

All features extracted directly from docs.litellm.ai (37 pages) and github.com/BerriAI/litellm on 2026-04-16.

## Feature Count by Domain

| Domain | Documented Features | CommandClaw Needs |
|---|---|---|
| API Endpoints | ~40 endpoint groups | 5 |
| Provider Support | 100+ providers, 2,500+ models | 5-7 providers |
| Routing | 6 strategies + ordering + weights | 2 strategies |
| Reliability | 4 fallback types + retries + cooldowns | Core set |
| Caching | 9 backends + per-request controls | Redis + in-memory |
| Virtual Keys | Key lifecycle, constraints, rotation | Core CRUD + constraints |
| Multi-Tenancy | 4-level hierarchy + RBAC | Keys + Users only |
| Cost Tracking | Per-request + aggregated + reports | Per-request + per-key |
| Rate Limiting | RPM/TPM per key/team/model | Per-key RPM/TPM |
| Observability | 40+ metrics, 25+ logging destinations, 15+ alert types | ~10 metrics, Langfuse, Slack |
| Guardrails | 8 providers, pre/post/during modes | Defer |
| Health Checks | 5 endpoints + background + cross-pod | Liveness + readiness |
| Deployment | Docker, K8s, Helm, Terraform, 6 cloud platforms | Docker Compose |
| Admin UI | Key mgmt, model mgmt, spend tracking, AI Hub | Skip |
| A2A Gateway | Agent protocol, JSON-RPC 2.0 | Skip (own routing) |
| MCP Gateway | Tool listing/calling, 3 transports, 6 auth methods | Skip (commandclaw-mcp) |

## Key Architectural Observations

1. LiteLLM has grown from "LLM proxy" into a full AI platform — the proxy functionality is maybe 30% of the codebase now.

2. The provider adapter pattern (BaseConfig with transform_request/transform_response) is clean and worth replicating. Each adapter is ~100-200 lines.

3. The Router class is the core value — routing strategies, cooldown tracking, retry logic. This is ~1,000-1,500 lines of Python for the features we need.

4. The virtual key system depends on PostgreSQL (LiteLLM_VerificationTokenTable) — this is the primary reason LiteLLM requires its own database. A Redis-only approach is viable for CommandClaw's scale.

5. The Prometheus metrics catalog is the most valuable reference artifact — it defines exactly which metrics are useful for LLM gateway monitoring.

6. The caching system supports 9 backends but the core logic (hash prompt → lookup → return or miss) is simple. Semantic caching adds embedding compute overhead that isn't justified yet.

7. JWT/OIDC auth is enormous (15+ config params, multiple mapping strategies) but entirely separate from the core gateway. Can be bolted on later.

8. The guardrails system is well-designed (provider-agnostic, multi-mode) but no current compliance requirement triggers it.

9. Pass-through endpoints (15+ providers) exist because LiteLLM tries to support every provider's native API format. CommandClaw standardizes on OpenAI-compat, eliminating this need.

10. The A2A and MCP gateway features represent LiteLLM expanding laterally into agent infrastructure — exactly what commandclaw-mcp already handles.
