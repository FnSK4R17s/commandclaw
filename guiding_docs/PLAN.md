# CommandClaw Week One Prototype — Implementation Plan

## Context

CommandClaw is a Git-native AI agent platform — a ground-up Python redesign of OpenClaw focused on enterprise reliability and control. The vault (Git repo), not chat, is the control plane. Week One delivers: agent execution loop, Telegram I/O, vault system, skill discovery, MCP gateway, Langfuse tracing, and one working coding agent.

## Repositories

| Repo | Purpose | Status |
|------|---------|--------|
| [commandclaw](https://github.com/FnSK4R17s/commandclaw) | Agent runtime, Telegram I/O, tracing | Guiding docs done, code pending |
| [commandclaw-mcp](https://github.com/FnSK4R17s/commandclaw-mcp) | MCP gateway — credential proxy with rotating keys | ✅ README done, code pending |
| [commandclaw-skills](https://github.com/FnSK4R17s/commandclaw-skills) | Skills library — `npx skills add FnSK4R17s/commandclaw-skills` | ✅ Done (bash, github, file-ops) |
| [commandclaw-vault](https://github.com/FnSK4R17s/commandclaw-vault) | Vault template — clone to create a new agent | ✅ Done (Obsidian pre-configured) |

## Project Structure (commandclaw)

```
/apps/commandclaw/
├── guiding_docs/
│   ├── VISION.md                    # ✅ Architecture and scope
│   └── PLAN.md                      # ✅ This file
├── README.md                        # ✅ Quick start, repos, architecture
├── pyproject.toml
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── scripts/
│   └── migrate-from-openclaw.sh     # Migration script for OpenClaw workspaces
├── src/commandclaw/
│   ├── __init__.py
│   ├── __main__.py                  # Entry point
│   ├── config.py                    # Pydantic Settings from env vars
│   ├── vault/
│   │   ├── __init__.py
│   │   ├── git_ops.py              # VaultRepo: commit, discard, audit
│   │   ├── agent_config.py         # Parse AGENTS.md (frontmatter + markdown body)
│   │   ├── identity.py             # Parse IDENTITY.md, SOUL.md, USER.md, TOOLS.md
│   │   ├── memory.py               # Read/write MEMORY.md + memory/*.md, git-commit on write
│   │   ├── skills.py               # Discover .agents/skills/*/SKILL.md, load on demand
│   │   └── recovery.py             # Discard uncommitted on fatal failure
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── runtime.py              # LangChain AgentExecutor — the core loop
│   │   ├── prompt.py               # System prompt builder (config + memory + skills)
│   │   ├── retry.py                # 3 retries, exponential backoff
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── bash_tool.py        # subprocess.run with timeout
│   │       ├── file_read.py        # Read files (path-validated)
│   │       ├── file_write.py       # Write files (path-validated)
│   │       ├── vault_memory.py     # memory_read / memory_write tools
│   │       └── vault_skill.py      # read_skill tool
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── client.py               # Connect to commandclaw-mcp gateway via rotating key
│   │   └── tools.py                # Wrap MCP tools as LangChain tools
│   ├── telegram/
│   │   ├── __init__.py
│   │   ├── bot.py                  # Bot setup + polling loop
│   │   ├── handlers.py             # Message → agent dispatch + retry + alerts
│   │   └── sender.py               # Chunked message sending, failure alerts
│   └── tracing/
│       ├── __init__.py
│       └── langfuse_tracing.py     # Langfuse CallbackHandler for LangChain
└── tests/
    ├── test_vault_*.py
    ├── test_agent_runtime.py
    └── test_retry.py
```

## Vault Structure (commandclaw-vault)

```
commandclaw-vault/                   # Clone to create a new agent
├── AGENTS.md                        # Workspace rules, session protocol, safety
├── SOUL.md                          # Agent personality, values, communication style
├── IDENTITY.md                      # Name, creature type, vibe, emoji, avatar
├── USER.md                          # Human's context and preferences
├── TOOLS.md                         # Local environment notes (SSH, devices, etc.)
├── HEARTBEAT.md                     # Recurring patterns, scheduled checks
├── BOOTSTRAP.md                     # First-run setup (deletes itself + README after bootstrap)
├── MEMORY.md                        # Curated long-term memory
├── README.md                        # Template readme (deleted on bootstrap)
├── memory/                          # Daily session logs (YYYY-MM-DD.md)
├── Attachments/                     # File attachments
├── _templates/                      # Obsidian Templater templates
│   └── DailyNote.md
├── _fileClasses/                    # Metadata Menu fileClasses
├── .commandclaw/
│   └── workspace-state.json         # Onboarding/bootstrap state
├── .obsidian/                       # Pre-configured for Obsidian app
│   ├── app.json                     # Markdown links, source mode, frontmatter visible
│   ├── appearance.json              # Dark theme
│   ├── community-plugins.json
│   ├── core-plugins.json
│   └── plugins/
│       ├── obsidian-git/            # Auto-commit 5min, auto-push, pull on boot
│       ├── templater-obsidian/      # Folder templates (memory/ → DailyNote.md)
│       ├── metadata-menu/           # fileClasses in _fileClasses/, frontmatter-first
│       └── obsidian-linter/         # YAML key sort, created/updated timestamps
└── .agents/
    └── skills/                      # Installed via `npx skills add FnSK4R17s/commandclaw-skills`
```

## Dependencies

- `langchain` + `langchain-openai` — agent framework + OpenAI provider
- `python-telegram-bot` — Telegram I/O (async, stable, well-documented)
- `langfuse` — observability with built-in LangChain callback
- `gitpython` — Git operations on vault repos
- `pydantic` + `pydantic-settings` — config validation
- `python-frontmatter` — parse YAML frontmatter from markdown
- `python-dotenv` — load .env files
- `mcp` — MCP client SDK (Model Context Protocol)

## Build Phases

### Phase 1 — Foundation
1. `pyproject.toml` — project setup + dependencies
2. `config.py` — Pydantic Settings (all env vars)
3. `vault/git_ops.py` — VaultRepo class
4. `vault/agent_config.py` — parse AGENTS.md
5. `vault/identity.py` — parse IDENTITY.md, SOUL.md, USER.md, TOOLS.md, HEARTBEAT.md
6. `vault/memory.py` — read/write MEMORY.md + memory/YYYY-MM-DD.md with git commits
7. `vault/skills.py` — discover .agents/skills/*/SKILL.md, load on demand
8. `vault/recovery.py` — git-based recovery

### Phase 2 — Agent Runtime
9. `agent/tools/*` — bash, file_read, file_write, vault_memory, vault_skill
10. `agent/prompt.py` — system prompt builder
11. `agent/runtime.py` — LangChain AgentExecutor loop
12. `agent/retry.py` — retry wrapper

### Phase 3 — MCP Gateway (commandclaw-mcp repo)
13. Gateway server — accepts agent connections via rotating hourly keys, proxies to real MCP servers
14. Key rotation — generate/expire agent keys on a configurable interval (default 1h)
15. RBAC — per-agent access control (which agent sees which MCP tools)
16. Audit logging — log every tool call (agent, tool, timestamp, inputs)

### Phase 3b — MCP Client (commandclaw repo)
17. `mcp/client.py` — connect to commandclaw-mcp gateway using rotating key, discover available tools
18. `mcp/tools.py` — wrap MCP tools as LangChain tools, wire into AgentExecutor alongside native tools

### Phase 4 — Telegram
19. `telegram/sender.py` — outbound messages + chunking
20. `telegram/handlers.py` — message routing + error handling
21. `telegram/bot.py` — bot setup + polling
22. `__main__.py` — entry point

### Phase 5 — Observability & Deployment
23. `tracing/langfuse_tracing.py` — wire into runtime
24. `Dockerfile` + `docker-compose.yml`
25. `.env.example`
26. `scripts/migrate-from-openclaw.sh` — OpenClaw workspace migration ✅

### Done ✅
- Vault template repo (`commandclaw-vault`) — all workspace files, Obsidian plugins pre-configured
- Skills repo (`commandclaw-skills`) — bash, github, file-ops skills
- MCP gateway repo (`commandclaw-mcp`) — README with security model and config spec
- Guiding docs — VISION.md, PLAN.md, README.md
- Migration script — tested against live OpenClaw workspace, preserves `skills-lock.json` (see [#1](https://github.com/FnSK4R17s/commandclaw/issues/1))

## OpenClaw Compatibility

The vault structure mirrors OpenClaw's workspace layout — same file names, same folder hierarchy. This means:

- **Easy migration** — run `scripts/migrate-from-openclaw.sh` to convert an OpenClaw workspace
- **Familiar to OpenClaw users** — AGENTS.md, SOUL.md, IDENTITY.md, etc. are all in the same places
- **Skills portability** — `.agents/skills/*/SKILL.md` follows the same discovery pattern
- **Memory portability** — `MEMORY.md` + `memory/YYYY-MM-DD.md` daily logs carry over

**Migration script** (`scripts/migrate-from-openclaw.sh`) handles:
1. Rename `.openclaw/` → `.commandclaw/`
2. Move `skills/` → `.agents/skills/` (if skills are at workspace root)
3. Validate vault structure post-migration
4. Initialize as a Git repo if not already one

## Key Design Decisions

- **Three separate repos** — main project, skills, vault template. Clean separation of concerns.
- **Fresh AgentExecutor per invocation** — vault IS the state, no leaks between runs
- **No LangChain memory module** — memory is markdown files in git, read as system prompt context
- **`create_openai_tools_agent`** — native function calling, more reliable than ReAct
- **One bot = one agent** for week one — multi-agent routing is week two
- **subprocess for bash** — Docker provides containment, proper sandbox is week two
- **Asyncio lock per chat_id** — prevents concurrent execution for same user
- **Skills fetched, not shipped** — `npx skills add FnSK4R17s/commandclaw-skills`, not hardcoded
- **Obsidian-native vaults** — pre-configured plugins for git sync, templates, frontmatter, linting
- **MCP gateway as a separate service** — agents never see real credentials. The `commandclaw-mcp` gateway holds all API keys and proxies tool calls. Agents authenticate with rotating hourly keys — even if leaked, they expire within 60 minutes. RBAC is enforced at the gateway (unauthorized tools are invisible). Config lives at `~/.commandclaw/mcp.json` (outside the vault, out of Git).

## Verification

1. Unit tests: vault parsing, memory read/write, skill discovery, retry logic
2. Integration test: send a Telegram message, agent reads vault, uses tools, responds
3. Langfuse dashboard: verify traces show LLM calls, tool calls, and timing
4. Recovery test: corrupt vault state, verify agent recovers and alerts user
5. MCP test: configure an MCP server, verify agent discovers and calls MCP tools
