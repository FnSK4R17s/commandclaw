# commandclaw-skills — the official skills library

> Skills are markdown files that describe agent capabilities. Install them into any vault.

## Why it exists

Every agent needs the same handful of foundational capabilities: run bash, read/write files, operate on git, interact with GitHub, and so on. Duplicating those instructions in every vault is tedious and drift-prone — if you improve the "don't run `rm -rf` on a non-empty path without confirmation" rule, you want that improvement to land in every agent at once.

`commandclaw-skills` is the upstream library of reusable skills. A vault installs skills with `npx skills add FnSK4R17s/commandclaw-skills` and gets the current canonical version of each, written into `.agents/skills/<skill-name>/SKILL.md`. Upgrading is the same command.

It is **not a code library**. It is a markdown library. The runtime reads SKILL.md, injects it into context, and the LLM follows the instructions. No plugin API, no import cycles, no version mismatches.

## What it does

| Capability | Detail |
|---|---|
| **Skill distribution** | `npx skills add` pulls skills from this repo into a vault's `.agents/skills/`. |
| **Selective install** | CLI prompts let you pick which skills to install per vault. |
| **Versioning** | Skills versioned via git (tags + commits). A vault's `skills-lock.json` pins versions. |
| **Frontmatter contract** | Every `SKILL.md` begins with YAML frontmatter: `name`, `description`. Runtime uses these for discovery. |

Current skills:

| Skill | Description |
|---|---|
| `bash` | Execute shell commands safely with timeouts and safety rules. |
| `github` | GitHub operations via `gh` CLI — PRs, issues, reviews, pushes. |
| `file-ops` | Read, write, and manage files in the workspace. |

## Tech stack and why

| Choice | Reason |
|---|---|
| **Markdown + YAML frontmatter** | Minimum viable "plugin" format. No build step, no runtime ABI, readable by any LLM. |
| **Agent Skills convention** | Compatible with Claude Agent Skills format — describe-and-activate via frontmatter `description`, full instructions in the body. |
| **`npx skills` CLI** | Zero install (uses `npx`), works cross-platform, familiar to any Node dev. |
| **Git as the registry** | The repo *is* the registry. Branch / tag / fork as needed. No hosted index. |
| **No code in skills** | Skills are prompts, not programs. Logic lives in the runtime or in tools the skill calls. |

## Internal architecture

```
commandclaw-skills/
└── skills/
    ├── bash/
    │   └── SKILL.md       ─── frontmatter: name, description
    │                          body: safety rules, patterns, examples
    ├── github/
    │   └── SKILL.md
    └── file-ops/
        └── SKILL.md
```

Every skill directory can optionally include auxiliary files (templates, reference notes, scripts) alongside `SKILL.md`. The CLI installs the whole directory verbatim.

## External interfaces

| Interface | Direction | Used for |
|---|---|---|
| **`npx skills add <github-slug>`** | user → repo | Pulls skill directories into a vault's `.agents/skills/`. |
| **Filesystem read** | [runtime](commandclaw.md) ← `.agents/skills/` | `list_skills` tool enumerates installed skills from the vault; frontmatter feeds skill discovery. |
| **GitHub (as a registry)** | `npx skills` ↔ GitHub raw | Fetches skill files. |

## Deployment shape

There is no deployment. It's a git repo. The CLI on the vault side pulls from it.

```bash
# inside a vault
npx skills add FnSK4R17s/commandclaw-skills
# select which skills to install
# → .agents/skills/bash/SKILL.md
# → .agents/skills/github/SKILL.md
# → .agents/skills/file-ops/SKILL.md
```

A `skills-lock.json` at the vault root records which version of each skill was installed, making upgrades diffable.

## Why a skills repo over alternatives

| Alternative | Why we didn't |
|---|---|
| **Hardcode skills in the runtime** | Every skill change requires a runtime release and every agent to pull the new image. |
| **Skills as Python plugins** | Adds an ABI, a version matrix, and an attack surface. LLMs don't need an ABI — they need instructions. |
| **Skills in the vault template** | Would lock the skill set to whenever you cloned the template. Upgrading is hard. |
| **A hosted registry** | Git already works as a registry. Adding a new system would be all cost, no benefit. |

## Related repos

See [commandclaw.md](commandclaw.md) for how the runtime discovers and uses skills, and [commandclaw-vault.md](commandclaw-vault.md) for where `.agents/skills/` lives.

## Key files

- [skills/bash/SKILL.md](https://github.com/FnSK4R17s/commandclaw-skills/blob/main/skills/bash/SKILL.md)
- [skills/github/SKILL.md](https://github.com/FnSK4R17s/commandclaw-skills/blob/main/skills/github/SKILL.md)
- [skills/file-ops/SKILL.md](https://github.com/FnSK4R17s/commandclaw-skills/blob/main/skills/file-ops/SKILL.md)
