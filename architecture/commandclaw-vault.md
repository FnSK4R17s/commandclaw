# commandclaw-vault — the agent template repo

> What an agent *is*, as files. Clone this repo to make a new agent.

## Why it exists

An agent needs an identity, a personality, rules of engagement, memory, and knowledge of its local environment. In most frameworks these live in code, a database, or a config UI. That makes them invisible to git, impossible to diff, and tedious to audit.

`commandclaw-vault` pushes all of it into plain markdown in a git repo. The vault *is* the agent. Clone the vault → you have an agent. Commit to the vault → you've changed the agent. Delete the vault → the agent is gone (but retrievable from git history).

This is the opposite of the typical "agent framework configuration" — which is usually a YAML in a repo, loaded by an engine that owns the real state. Here there is no hidden state.

## What it does

It is **data, not code**. The repo ships:

| File | What it is | Who edits it |
|---|---|---|
| `AGENTS.md` | Workspace rules, session protocol, safety guidelines. | You (rules) + agent (occasional amendments) |
| `SOUL.md` | Personality, values, communication style. | You |
| `IDENTITY.md` | Name, creature type, vibe, emoji. Filled in on first run. | Agent (first boot), you (later) |
| `USER.md` | Human context and preferences. | Agent learns this over time + you |
| `TOOLS.md` | Local environment notes — SSH hosts, devices, preferences. | You |
| `HEARTBEAT.md` | Recurring checks and proactive tasks. | You + agent |
| `BOOTSTRAP.md` | First-run instructions. Deleted after bootstrap. | Template author |
| `MEMORY.md` | Curated long-term memory. | Agent (distilled), you (corrections) |
| `memory/YYYY-MM-DD.md` | Daily session logs, auto-created. | Agent |
| `_fileClasses/` | Obsidian metadata-menu schemas for structured frontmatter. | You (rare) |
| `_templates/` | Templater templates for daily notes. | You (rare) |
| `Attachments/` | Images and media pasted in Obsidian. | Agent + you |

The runtime in [commandclaw](commandclaw.md) reads these on boot to assemble the system prompt and understand its context.

## Tech stack and why

| Choice | Reason |
|---|---|
| **Plain markdown** | Human-readable, diff-readable, grep-readable. No parsing lock-in; fallback is always `cat`. |
| **Obsidian config tracked in git** | `.obsidian/` plugin configs are in the repo so a fresh clone opens identically everywhere. Plugin *binaries* are gitignored (one-time install per machine). |
| **obsidian-git plugin** | Auto-commit every 5 min, auto-push, pull on boot. Means "I edited my agent in Obsidian" = "I committed to the agent's vault." |
| **templater** | New daily memory notes get a pre-filled frontmatter template. |
| **metadata-menu** | Structured frontmatter via `fileClasses` — enforces keys like `created`, `updated`, `tags` without coding it in the runtime. |
| **obsidian-linter** | YAML key sorting, automatic `created`/`updated` timestamps. Keeps diffs clean. |
| **Karpathy LLM-Wiki influence** | The long-term memory structure follows the same pattern the [commandclaw-wiki](commandclaw-wiki.md) uses, just scoped to a single agent. |
| **No code** | The vault is intentionally passive. If logic is needed, it lives in the runtime or a skill. |

## Internal architecture

There isn't one — it's a pile of markdown. But there is a **contract** with the runtime:

```
vault root/
├── AGENTS.md            ←── read into system prompt (rules)
├── SOUL.md              ←── read into system prompt (personality)
├── IDENTITY.md          ←── read into system prompt (name/vibe)
├── USER.md              ←── read into system prompt (user context)
├── TOOLS.md             ←── read into system prompt (environment)
├── HEARTBEAT.md         ←── polled by scheduled checks
├── MEMORY.md            ←── read into system prompt (long-term)
├── memory/
│   └── YYYY-MM-DD.md   ←── current session log, appended during chat
├── .agents/skills/      ←── skills installed via `npx skills add ...`
│   └── <skill-name>/SKILL.md
├── _fileClasses/        ←── metadata-menu schemas
├── _templates/          ←── templater templates
└── .obsidian/           ←── Obsidian plugin config (tracked)
```

The runtime resolves the vault path from the agent ID (`~/.commandclaw/workspaces/<agent-id>`), bind-mounts it into the container at `/workspace`, and reads the files above on every turn.

## External interfaces

| Interface | Direction | Used for |
|---|---|---|
| **Filesystem (bind mount)** | runtime ↔ vault | Read config + skills, write memory. |
| **git** | vault ↔ remote (GitHub, private server, local bare) | Backup, sync, audit, fork. |
| **Obsidian** | user ↔ vault | Human-facing edit surface. |
| **`npx skills add FnSK4R17s/commandclaw-skills`** | installer | Pull skills from [commandclaw-skills](commandclaw-skills.md) into `.agents/skills/`. |

## Deployment shape

The vault is a git repo. Nothing runs. The runtime does.

```
gh repo clone FnSK4R17s/commandclaw-vault my-agent
cd my-agent
npx skills add FnSK4R17s/commandclaw-skills
# → agent is ready, runtime can boot against it
```

## Why this structure over alternatives

| Alternative | Why we didn't |
|---|---|
| **Config in a database** | No diff, no fork, no offline audit. |
| **YAML/JSON config loaded by runtime** | Fine for flat settings, but markdown is a better medium for the personality + rules + memory mix. |
| **One big config file** | Reviewing a single 5000-line file is harder than reviewing eight 100-line files. |
| **A UI** | UIs are great for reading, terrible for audit and diff. |

The vault wins on every axis that matters for a long-running, multi-user, multi-agent system: versioning, auditability, portability, and the ability to fork.

## Key files in the template

- [AGENTS.md](https://github.com/FnSK4R17s/commandclaw-vault/blob/main/AGENTS.md) — the rules
- [SOUL.md](https://github.com/FnSK4R17s/commandclaw-vault/blob/main/SOUL.md) — the personality
- [BOOTSTRAP.md](https://github.com/FnSK4R17s/commandclaw-vault/blob/main/BOOTSTRAP.md) — first-run flow
- [_fileClasses/](https://github.com/FnSK4R17s/commandclaw-vault/tree/main/_fileClasses) — frontmatter schemas
