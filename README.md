<p align="center">
  <span style="font-size: 100px;">⚓🦞</span>
</p>

<h1 align="center">Command Claw</h1>

<p align="center">
  <strong>Git-native agent platform built for enterprise reliability and control.</strong><br>
  <em>A ground-up redesign of OpenClaw — your vault commands the agents, not the other way around.</em><br>
  <sub>Configuration, memory, and behavior rules live in files you can inspect, edit, version, and audit.</sub>
</p>

---

## Quick Start

```bash
# 1. Clone the vault template to create a new agent
gh repo clone FnSK4R17s/commandclaw-vault my-agent

# 2. Install skills (select which ones to add)
cd my-agent
npx skills add FnSK4R17s/commandclaw-skills

# 3. Open in Obsidian (plugins are pre-configured)
```

## Repositories

| Repo | Purpose |
|------|---------|
| [commandclaw](https://github.com/FnSK4R17s/commandclaw) | Main project — agent runtime, Telegram I/O, tracing |
| [commandclaw-skills](https://github.com/FnSK4R17s/commandclaw-skills) | Skills library — `npx skills add FnSK4R17s/commandclaw-skills` |
| [commandclaw-vault](https://github.com/FnSK4R17s/commandclaw-vault) | Vault template — clone to create a new agent |

## Why Python?

CommandClaw is I/O-bound, not CPU-bound. The agent spends 99%+ of its time waiting on external calls — LLM API responses (1-10s), subprocess execution, file I/O, Git operations, and Telegram API calls. Python's runtime speed is irrelevant here.

Python was chosen over TypeScript because:

- **LangChain's Python ecosystem is larger** — more integrations, better documentation, and first-class Langfuse support.
- **Clean break from OpenClaw** — avoids inheriting patterns or dependencies from the codebase we're replacing.
- **Simpler deployment** — single `pip install`, no build step, no bundler config.

## Architecture

See [guiding_docs/VISION.md](guiding_docs/VISION.md) for the full vision and [guiding_docs/PLAN.md](guiding_docs/PLAN.md) for the Week One implementation plan.

**Three layers:**

1. **Agent Runtime** — LangChain + OpenAI execution loop. Each agent runs independently with its own Git vault.
2. **Skills Layer** — Markdown files describing agent capabilities. Managed by admins, not agents.
3. **MCP Layer** — Authentication-gated sensitive operations with access control at the protocol level.

**Core principle:** The vault (Git repo) is the control plane, not chat. Configuration, memory, and behavior rules live in files you can inspect, edit, version, and audit.

## Skills

Skills are markdown files in `.agents/skills/` within each agent's vault. They describe capabilities the agent can use — the agent reads skill descriptions into context and loads full instructions on demand.

**Install skills from the [commandclaw-skills](https://github.com/FnSK4R17s/commandclaw-skills) repo:**

```bash
# Install skills into the current vault (select which ones to add)
npx skills add FnSK4R17s/commandclaw-skills
```

Skills are managed by administrators, not agents. Agents can read and use skills but cannot install, update, or remove them. No skills ship with the vault by default — install what your agent needs.

## MCP

Agents connect to external [MCP](https://modelcontextprotocol.io/) servers and use their tools alongside native ones (bash, file read/write, etc.). MCP tools are discovered automatically and appear in the agent's tool list.

**Configuration lives outside the vault** — API keys and tokens never touch Git:

```
~/.commandclaw/mcp.json
```

Override the path with `COMMANDCLAW_MCP_CONFIG` env var.

```json
{
  "servers": {
    "notion": {
      "command": "npx",
      "args": ["-y", "@notionhq/notion-mcp-server"],
      "env": { "NOTION_API_KEY": "ntn_..." }
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "ghp_..." }
    }
  }
}
```

## Migrating from OpenClaw

CommandClaw's vault structure is compatible with OpenClaw workspaces. Run the migration script to convert:

```bash
./scripts/migrate-from-openclaw.sh /path/to/openclaw/workspace /path/to/commandclaw/vault
```

This handles renaming `.openclaw/` to `.commandclaw/`, moving `skills/` into `.agents/skills/`, and validating the vault structure.
