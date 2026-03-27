# CommandClaw Week One Prototype — Implementation Plan

## Context

CommandClaw is a Git-native AI agent platform — a ground-up Python redesign of OpenClaw focused on enterprise reliability and control. The vault (Git repo), not chat, is the control plane. Week One delivers: agent execution loop, Telegram I/O, vault system, skill discovery, Langfuse tracing, and one working coding agent.

## Project Structure

```
/apps/commandclaw/
├── guiding_docs/VISION.md           # Already exists
├── pyproject.toml
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── scripts/
│   └── migrate-from-openclaw.sh    # Migration script for OpenClaw workspaces
├── src/commandclaw/
│   ├── __init__.py
│   ├── __main__.py                  # Entry point
│   ├── config.py                    # Pydantic Settings from env vars
│   ├── vault/
│   │   ├── __init__.py
│   │   ├── git_ops.py              # VaultRepo: commit, discard, audit
│   │   ├── agent_config.py         # Parse AGENTS.md (frontmatter + markdown body)
│   │   ├── identity.py            # Parse IDENTITY.md, SOUL.md, USER.md, TOOLS.md
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
│   ├── telegram/
│   │   ├── __init__.py
│   │   ├── bot.py                  # Bot setup + polling loop
│   │   ├── handlers.py             # Message → agent dispatch + retry + alerts
│   │   └── sender.py               # Chunked message sending, failure alerts
│   └── tracing/
│       ├── __init__.py
│       └── langfuse_tracing.py     # Langfuse CallbackHandler for LangChain
├── tests/
│   ├── test_vault_*.py
│   ├── test_agent_runtime.py
│   └── test_retry.py
└── example_vault/                   # Coding agent vault (mirrors OpenClaw workspace)
    ├── AGENTS.md                    # Repo guidelines, coding style, build commands
    ├── SOUL.md                      # Agent personality, values, communication style
    ├── IDENTITY.md                  # Name, creature type, vibe, emoji, avatar
    ├── USER.md                      # Human's context and preferences
    ├── TOOLS.md                     # Local environment notes (SSH, devices, etc.)
    ├── HEARTBEAT.md                 # Recurring patterns, scheduled checks
    ├── BOOTSTRAP.md                 # First-run setup (optional, deleted after first read)
    ├── MEMORY.md                    # Curated long-term memory
    ├── memory/                      # Daily session logs
    │   └── YYYY-MM-DD.md
    ├── .commandclaw/
    │   └── workspace-state.json     # Onboarding/bootstrap state
    ├── .obsidian/                   # Pre-configured for Obsidian app
    │   ├── app.json                 # Markdown links, source mode, frontmatter visible
    │   ├── appearance.json          # Dark theme
    │   ├── community-plugins.json   # Plugin manifest
    │   ├── core-plugins.json        # Core plugin toggles
    │   └── plugins/
    │       ├── obsidian-git/        # Auto-commit, auto-push, auto-pull on boot
    │       ├── templater-obsidian/  # Folder-based templates for vault files
    │       ├── metadata-menu/       # Structured frontmatter with fileClasses
    │       └── obsidian-linter/     # YAML key sorting, created/updated timestamps
    └── .agents/
        └── skills/                  # Installed via `npx skills add` from commandclaw-skills repo
            └── (empty — skills fetched on vault init, not shipped)
```

## Dependencies

- `langchain` + `langchain-openai` — agent framework + OpenAI provider
- `python-telegram-bot` — Telegram I/O (async, stable, well-documented)
- `langfuse` — observability with built-in LangChain callback
- `gitpython` — Git operations on vault repos
- `pydantic` + `pydantic-settings` — config validation
- `python-frontmatter` — parse YAML frontmatter from markdown
- `python-dotenv` — load .env files

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
8. `agent/tools/*` — bash, file_read, file_write, vault_memory, vault_skill
9. `agent/prompt.py` — system prompt builder
10. `agent/runtime.py` — LangChain AgentExecutor loop
11. `agent/retry.py` — retry wrapper

### Phase 3 — Telegram
12. `telegram/sender.py` — outbound messages + chunking
13. `telegram/handlers.py` — message routing + error handling
14. `telegram/bot.py` — bot setup + polling
15. `__main__.py` — entry point

### Phase 4 — Observability & Deployment
16. `tracing/langfuse_tracing.py` — wire into runtime
17. `example_vault/` — coding agent vault content + `.obsidian/` pre-configured
18. `Dockerfile` + `docker-compose.yml`
19. `.env.example`
20. `scripts/migrate-from-openclaw.sh` — OpenClaw workspace migration

### Obsidian Plugin Configuration (ships with example_vault)

Every vault comes pre-configured to work as an Obsidian vault out of the box:

| Plugin | Config |
|--------|--------|
| **obsidian-git** | Auto-commit every 5min, auto-push, auto-pull on boot, merge sync |
| **templater-obsidian** | Folder templates for `memory/`, `.agents/skills/` |
| **metadata-menu** | fileClasses in `_fileClasses/`, frontmatter-first |
| **obsidian-linter** | YAML key sort, auto `created`/`updated` timestamps |

**Core Obsidian settings:**
- Markdown links (not wiki), shortest path
- Attachments in `Attachments/`
- Source mode default, frontmatter visible
- Dark theme

## OpenClaw Compatibility

The vault structure mirrors OpenClaw's workspace layout — same file names, same folder hierarchy. This means:

- **Easy migration** — run `scripts/migrate-from-openclaw.sh` to convert an OpenClaw workspace into a CommandClaw vault
- **Familiar to OpenClaw users** — AGENTS.md, SOUL.md, IDENTITY.md, etc. are all in the same places
- **Skills portability** — `.agents/skills/*/SKILL.md` follows the same discovery pattern, installed via `npx skills add` from [commandclaw-skills](https://github.com/FnSK4R17s/commandclaw-skills)
- **Memory portability** — `MEMORY.md` + `memory/YYYY-MM-DD.md` daily logs carry over

**Migration script** (`scripts/migrate-from-openclaw.sh`) handles:
1. Rename `.openclaw/` → `.commandclaw/`
2. Move `skills/` → `.agents/skills/` (if skills are at workspace root)
3. Validate vault structure post-migration
4. Initialize as a Git repo if not already one

## Key Design Decisions

- **Fresh AgentExecutor per invocation** — vault IS the state, no leaks between runs
- **No LangChain memory module** — memory is markdown files in git, read as system prompt context
- **`create_openai_tools_agent`** — native function calling, more reliable than ReAct
- **One bot = one agent** for week one — multi-agent routing is week two
- **subprocess for bash** — Docker provides containment, proper sandbox is week two
- **Asyncio lock per chat_id** — prevents concurrent execution for same user

## Verification

1. Unit tests: vault parsing, memory read/write, skill discovery, retry logic
2. Integration test: send a Telegram message, agent reads vault, uses tools, responds
3. Langfuse dashboard: verify traces show LLM calls, tool calls, and timing
4. Recovery test: corrupt vault state, verify agent recovers and alerts user
