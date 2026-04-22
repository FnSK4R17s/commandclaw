# commandclaw — the agent runtime

> The process that actually runs. Reads from a vault, talks to LLMs and tools through proxies, streams back to the user.

## Why it exists

Modern agent frameworks make one of two trade-offs: either the agent's configuration is buried in code (fast to build, impossible to audit) or it lives in a UI/database (easy to click through, impossible to version). Neither works for teams that need to know exactly what an agent will do *before* it runs, and exactly what it did *after*.

`commandclaw` is the runtime for a git-native agent — one whose system prompt, personality, skills, memory, and behavior rules all live as files in a git repository you clone per agent. Change the agent by committing to its vault. Audit the agent by reading its vault. Fork the agent by cloning its vault.

It is a ground-up redesign of [openclaw](openclaw.md) with enterprise controls baked in from day one: phantom tokens for tool credentials, virtual keys for LLM access, filesystem-isolated Docker execution, full Langfuse tracing, and guardrails via Presidio + NeMo.

## What it does

| Capability | Detail |
|---|---|
| **Vault-driven configuration** | Every agent has a personal vault (`~/.commandclaw/workspaces/<agent-id>/`) cloned from [commandclaw-vault](commandclaw-vault.md). Files like `AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md` are read by the runtime on boot. |
| **Chat loop** | CLI chat or Telegram webhook. LangGraph state machine with retry, tool execution, streaming. |
| **Tool execution** | Bash, file I/O (scoped to `/workspace`), vault memory, skill registry. MCP tools via the [MCP gateway](commandclaw-mcp.md). |
| **Isolation** | Each agent runs in its own Docker container: 512MB RAM, 1 CPU, read-only root, tmpfs for scratch, vault bind-mounted at `/workspace`. |
| **Agent naming** | `adjective-animal-NNNN` (chakravarti-cli convention) — stable, memorable, greppable. |
| **Memory** | Daily notes and long-term MEMORY.md, auto-committed to the vault on every write. |
| **Guardrails** | Presidio (PII detection + redaction), NeMo Guardrails config, bashlex command linting, detect-secrets. |
| **Tracing** | Full Langfuse integration — LLM calls, tool calls, graph state transitions. |

## Tech stack and why

| Choice | Reason |
|---|---|
| **Python 3.11+** | LangGraph/LangChain ecosystem is Python-native. `target-version = "py311"` in ruff config. |
| **LangChain + LangGraph ≥1.1** | LangGraph gives an explicit state machine for the chat loop — retries, tool calls, and branching are graph edges instead of hidden control flow. Checkpoints via `langgraph-checkpoint-sqlite`. |
| **python-telegram-bot** | Telegram is the default non-terminal surface. Single, well-maintained library for webhooks, updates, and media. |
| **MCP** | Tools are MCP tools. Means every external integration is pluggable and uses the same wire protocol. The runtime is an MCP *client* talking to [commandclaw-mcp](commandclaw-mcp.md) as the server. |
| **Langfuse v4 SDK** | First-class tracing of LLM calls, tool calls, and graph state. Self-host via [commandclaw-observe](commandclaw-observe.md) or use cloud. |
| **Presidio + NeMo Guardrails** | Defense-in-depth. Presidio catches PII with proven detectors; NeMo catches prompt-level policy violations. |
| **GitPython** | The vault is a git repo. Memory writes auto-commit. No bash shelling out for common ops. |
| **pydantic + pydantic-settings** | Settings from env (`COMMANDCLAW_*` prefix) with schema validation. Fail fast on boot, not at runtime. |
| **hatchling** | Minimal PEP 517 build backend. No unnecessary build machinery. |
| **Docker** | Isolation of untrusted agent bash. Matches the MCP gateway's network so agents reach tools without exposing the host. |

## Internal architecture

```
src/commandclaw/
├── __main__.py           CLI entry: `commandclaw chat`, `commandclaw telegram`, etc.
├── config.py             Pydantic settings (COMMANDCLAW_* env vars)
├── agent/
│   ├── graph.py          LangGraph state machine — nodes for prompt, tool, retry
│   ├── prompt.py         System-prompt assembly from vault files (AGENTS.md, SOUL.md, …)
│   ├── retry.py          Retry policy for tool failures and transient LLM errors
│   ├── runtime.py        Agent boot, lifecycle, vault resolution
│   └── tools/
│       ├── bash_tool.py      bashlex-linted shell execution
│       ├── file_read.py      Read a file in the vault
│       ├── file_write.py     Write + auto-commit
│       ├── file_list.py      List files and dirs
│       ├── file_delete.py    Delete + auto-commit
│       ├── vault_memory.py   memory_read / memory_write
│       ├── vault_skill.py    Skill discovery
│       ├── skill_registry.py Skill lookup + frontmatter parsing
│       └── system_info.py    Async system info (host, cwd, git state)
├── vault/                Vault clone management, workspace resolution
├── mcp/                  MCP client for commandclaw-mcp
├── telegram/             python-telegram-bot handlers
├── guardrails/           Presidio, NeMo, detect-secrets wiring
│   └── nemo_config/      NeMo Guardrails policy files
└── tracing/              Langfuse wiring
```

The shape is deliberately flat. Each concern is a package, each package exposes a small public surface, and the state machine in `agent/graph.py` is the only orchestrator.

## External interfaces

| Interface | Direction | Used for |
|---|---|---|
| **LLM over HTTP** | runtime → [commandclaw-gateway](commandclaw-gateway.md) | All LLM calls. OpenAI-format for ChatOpenAI, Anthropic-format for Anthropic. Virtual key only. |
| **MCP over HTTP/stdio** | runtime → [commandclaw-mcp](commandclaw-mcp.md) | Tool calls. Phantom token only. |
| **git** | runtime ↔ vault | Read config + skills, write memory, commit + push. |
| **Telegram HTTPS** | runtime ↔ Telegram | User messages, replies, media. |
| **Langfuse SDK** | runtime → [commandclaw-observe](commandclaw-observe.md) or Langfuse Cloud | Traces. |

## Deployment shape

```
~/.commandclaw/
├── workspaces/
│   ├── brave-panda-4821/       ← vault clone (one per agent)
│   └── swift-falcon-0137/      ← vault clone (one per agent)
├── mcp.json                     ← MCP gateway config (not in any repo)
└── .env                         ← secrets

docker network: commandclaw
  ├── agent-brave-panda-4821   (this repo's image)
  ├── agent-swift-falcon-0137  (this repo's image)
  ├── commandclaw-mcp           (commandclaw-mcp repo)
  └── commandclaw-gateway       (commandclaw-gateway repo)
```

The runtime image is intentionally small: it ships Python, the commandclaw package, and nothing else. All state — identity, memory, skills — is a bind mount from the vault. Kill the container and the agent is unchanged; rebuild the image without touching the vault and the agent inherits the upgrade.

## Key files

- [src/commandclaw/agent/graph.py](../src/commandclaw/agent/graph.py) — the state machine
- [src/commandclaw/agent/prompt.py](../src/commandclaw/agent/prompt.py) — how vault files become a system prompt
- [scripts/spawn-agent.sh](../scripts/spawn-agent.sh) — spawn / resume / list agents
- [Dockerfile](../Dockerfile) — agent container
- [docker-compose.yml](../docker-compose.yml) — full local stack
- [guiding_docs/VISION.md](../guiding_docs/VISION.md) — the long-form "why"
