# CommandClaw Architecture

This folder documents the **why** and **what** of every repo in the CommandClaw ecosystem — one file per repo, all following the same template: purpose, architectural rationale, tech stack, internal structure, external interfaces, and where it sits in the larger system.

Read this README for the high-level map. Drill into a per-repo file when you need detail.

---

## One-line mental model

> **The vault is the control plane. Everything else is a service that defers to it.**

A CommandClaw agent is a process that reads its instructions, memory, and tools from a git repository (the vault) and talks to LLMs and external tools through credential-isolating proxies. Nothing about the agent's behavior is baked into code — it's all files in a git repo you can inspect, edit, and version.

---

## The repos at a glance

| Repo | Role | Runtime | Primary tech |
|---|---|---|---|
| [commandclaw](commandclaw.md) | Agent runtime. The thing that actually thinks, chats, calls tools. | Python 3.11+ | LangChain / LangGraph, python-telegram-bot, MCP client, Docker |
| [commandclaw-vault](commandclaw-vault.md) | Template repo cloned into each agent's workspace. Defines what an agent *is*. | n/a (data) | Markdown, Obsidian, obsidian-git |
| [commandclaw-mcp](commandclaw-mcp.md) | MCP proxy. Agents hold phantom tokens; real credentials live here. | Python 3.12+ | FastAPI, FastMCP, Redis, Cerbos, OpenTelemetry |
| [commandclaw-gateway](commandclaw-gateway.md) | LLM routing layer. Virtual keys, budgets, rate limits, multi-provider fallback. | Python 3.11+ | FastAPI, httpx, Redis, tiktoken, Prometheus, Langfuse |
| [commandclaw-skills](commandclaw-skills.md) | Official skill library. Markdown files that describe agent capabilities. | n/a (data) | Markdown, YAML frontmatter, `npx skills` installer |
| [commandclaw-memory](commandclaw-memory.md) | Recall service. Owns the wiki repo, validates writes, runs hybrid search. | Python (planned) | FastAPI, LanceDB, Tantivy, Pydantic, Cerbos |
| [commandclaw-wiki](commandclaw-wiki.md) | LLM-maintained knowledge base. Persistent, compounding, human-readable. | n/a (data) | Markdown, Obsidian, Karpathy LLM-Wiki pattern |
| [commandclaw-observe](commandclaw-observe.md) | Self-hosted observability stack. Langfuse + Prometheus + Grafana in one compose. | Docker Compose | Langfuse v3, ClickHouse, Postgres, Redis, MinIO, Prometheus, Grafana |

---

## Why this split?

A single monolith would be simpler to ship. The repos are split because **each one has a different trust boundary, a different lifecycle, and a different deployment story**.

| Split | Reason |
|---|---|
| Runtime vs vault | Runtime is code; vault is data. An agent's identity should be portable across runtime versions and restorable from git. |
| Runtime vs MCP gateway | An agent that holds real API credentials is one prompt injection away from disaster. The gateway gives agents phantom tokens that rotate hourly. |
| Runtime vs LLM gateway | Provider credentials, budgets, rate limits, and cost tracking are ops concerns, not agent concerns. Centralizing them lets one team govern spend across every agent. |
| Runtime vs memory service | Cheap/weak models cannot be trusted to self-maintain a knowledge base. The memory service is the discipline layer — schema validation, atomic git commits, hybrid retrieval — so the agent can stay dumb and fast. |
| Memory service vs wiki | The service owns the write path. The wiki is the artifact. The artifact is git-native and portable even if the service disappears. |
| Skills as a separate repo | Skills are shared across every agent. Versioning them in one place means a skill upgrade lands everywhere without editing per-agent vaults. |
| Observe as a separate compose | Most users want hosted Langfuse + Grafana. The self-hosted stack is for teams with data-sovereignty requirements. Keeping it in its own compose means zero tax on everyone else. |

Each boundary is enforced at the wire: HTTP between services, git between the runtime and its vault, phantom tokens between agents and credentials.

---

## How a request flows

Concrete example: the agent receives a Telegram message and needs to read a file, look something up on the web, and respond.

```
Telegram user
    │
    ▼  (python-telegram-bot webhook)
commandclaw runtime
    │
    ├─► LangGraph state machine
    │       │
    │       ├─► LLM call ──► commandclaw-gateway ──► OpenAI/Anthropic/Vertex/Bedrock
    │       │                 (virtual key, budget,    (real credentials,
    │       │                  rate limit, cache,       returned response)
    │       │                  routing, fallbacks)
    │       │
    │       ├─► Tool: file_read ──► /workspace (the vault, mounted)
    │       │
    │       ├─► Tool: web_search ──► commandclaw-mcp ──► upstream MCP server
    │       │                        (phantom token,     (real API key,
    │       │                         RBAC policy,        results)
    │       │                         session pool)
    │       │
    │       └─► Tool: wiki_search ──► commandclaw-memory ──► LanceDB + Tantivy
    │                                 (validated reads,       over commandclaw-wiki
    │                                  hybrid retrieval)
    │
    ├─► Trace ──► Langfuse (in commandclaw-observe or hosted)
    ├─► Metrics ──► Prometheus
    └─► Auto-commit to vault (memory note, daily log)
```

Two guarantees fall out of this shape:

1. **An agent never holds real secrets.** Not for LLMs, not for tools. Leaks are bounded to a rotating phantom token.
2. **Every interesting state change is auditable.** Git history for the vault. Spend logs for LLM calls. Audit trail for admin ops. Traces for everything else.

---

## Shared conventions

- **Branding.** All repos use a common logo system (⚓🦞 base mark + per-repo suffix emoji). Defined in `commandclaw/branding.yml`, rendered by the `brand-kit` skill.
- **Commit style.** Conventional Commits, subject ≤50 chars, body explains *why*.
- **Language split.** Python for services (runtime, MCP gateway, LLM gateway, memory). Markdown for data (vault, wiki, skills). YAML for config. Docker Compose for deployment.
- **Secrets never enter a repo.** Config lives under `~/.commandclaw/` on the host; encryption seeds are generated by `make setup`.
- **One service, one job.** The runtime routes messages. The MCP gateway proxies tools. The LLM gateway routes models. The memory service owns the wiki. Resist the urge to merge them.

---

## Navigating the per-repo files

Each per-repo file in this folder answers the same five questions:

1. **Why does this exist?** — the problem it solves and the alternative it rejects.
2. **What does it do?** — capability surface.
3. **How is it built?** — tech stack and why those choices.
4. **Internal architecture** — modules, data flow, state.
5. **External interfaces** — the wire contract with the rest of the ecosystem.

Start with [commandclaw.md](commandclaw.md) if you want to understand the runtime, or [commandclaw-vault.md](commandclaw-vault.md) if you want to understand what an agent is made of.
