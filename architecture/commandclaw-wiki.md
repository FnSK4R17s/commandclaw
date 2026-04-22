# commandclaw-wiki — the LLM-maintained knowledge base

> You curate sources. The LLM builds the wiki. Knowledge compounds.

## Why it exists

Classic RAG re-derives knowledge from raw documents on every query. That means the same synthesis work, the same cross-referencing, the same contradiction-spotting — done from scratch, every time, forever. Expensive, slow, and nothing accumulates.

`commandclaw-wiki` follows Andrej Karpathy's [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern instead. When you add a source, the LLM reads it, extracts entities/concepts, integrates them into existing pages, flags contradictions, updates syntheses, and commits. The wiki is a **persistent, compounding artifact**: cross-references are already there, contradictions are already flagged, the synthesis reflects everything ingested so far.

The artifact is plain markdown in git. You can open it in Obsidian. You can diff it. You can fork it. You can read it without any LLM in the loop.

## What it does

It is **data, not code.** The repo ships a template for the wiki structure, a schema (`CLAUDE.md`) that tells the LLM how to maintain it, and a few helper scripts/hooks.

| File / dir | Purpose |
|---|---|
| `raw/` | Your sources. Immutable; the LLM only reads. Web-clipper output, papers, notes, transcripts. |
| `raw/sessions/` | Auto-captured Claude Code session transcripts for later distillation. |
| `raw/assets/` | Images, attachments. |
| `wiki/index.md` | Content catalog — the LLM's entry point for queries. |
| `wiki/log.md` | Append-only timeline of all wiki operations. |
| `wiki/overview.md` | High-level map of the wiki. |
| `wiki/sources/` | One page per ingested raw source. |
| `wiki/entities/` | People, orgs, products, places. |
| `wiki/concepts/` | Ideas, frameworks, terminology. |
| `wiki/comparisons/` | Side-by-side analyses. |
| `wiki/syntheses/` | Query answers worth keeping. |
| `wiki/templates/` | Obsidian Templater-compatible page templates. |
| `CLAUDE.md` | The schema. Tells the LLM how to maintain the wiki. |
| `PRD.md` | The original Karpathy pattern document. |
| `hooks/` | Local git hooks (e.g., capture-session-on-commit). |
| `scripts/` | Ingest helpers, lint scripts. |

## Tech stack and why

| Choice | Reason |
|---|---|
| **Plain markdown + frontmatter** | Human-readable, grep-able, Obsidian-compatible, fallback is `cat`. |
| **Git** | Versioning, fork, diff, backup — all for free. |
| **Obsidian** | Best-in-class wikilink graph surface for markdown. Opens the repo as-is. |
| **obsidian-git** | Auto-commit / auto-push so every LLM edit is recorded. |
| **templater** | Auto-fills frontmatter when a new page is created. |
| **metadata-menu** | Enforces structured frontmatter via `fileClasses`. |
| **obsidian-linter** | Keeps YAML diffs clean. |
| **obsidian-web-clipper** | Low-friction way to drop a web article into `raw/`. |
| **No engine** | The wiki is deliberately engine-less. Any LLM that understands the schema in `CLAUDE.md` can maintain it. |

## Internal architecture

The wiki has **three layers**:

```
┌──────────────────────────────────────────────┐
│  raw/               ← you curate             │
│  (immutable sources — LLM reads only)         │
└──────────────────────────────────────────────┘
                  │  (ingest)
                  ▼
┌──────────────────────────────────────────────┐
│  wiki/              ← LLM maintains          │
│  entities, concepts, comparisons, syntheses, │
│  sources, index.md, log.md, overview.md       │
└──────────────────────────────────────────────┘
                  ▲
                  │  (co-evolve)
┌──────────────────────────────────────────────┐
│  CLAUDE.md          ← you + LLM co-own       │
│  (schema: what pages exist, how they link,   │
│   how to resolve contradictions, etc.)        │
└──────────────────────────────────────────────┘
```

### Ingest flow (agent-driven)

```
new file in raw/
    ▼
"Ingest raw/<file>.md into the wiki"
    ▼
LLM reads source
    ▼
LLM updates pages:
  ├─ creates/updates an entity page
  ├─ creates/updates concept pages
  ├─ flags contradictions with existing syntheses
  ├─ appends a row to log.md
  └─ adjusts index.md
    ▼
git commit (via obsidian-git or scripted)
```

The same LLM can follow up with a synthesis — "compare X and Y given everything ingested" — which becomes a new page in `wiki/syntheses/`.

## External interfaces

| Interface | Direction | Used for |
|---|---|---|
| **git** | wiki ↔ remote | Backup, sync, versioning. |
| **Filesystem (owned clone)** | [commandclaw-memory](commandclaw-memory.md) ↔ wiki | Memory service owns the working clone; writes via its own discipline layer. |
| **Obsidian** | user ↔ wiki | Human-facing browse and edit. |
| **Web clipper** | browser → `raw/` | Drop web articles directly into the sources layer. |

## Deployment shape

None — it's a git repo. Two common topologies:

1. **Solo Obsidian workflow.** Clone the template, open in Obsidian, use Claude Code (or any LLM) against it directly. Minimal setup.
2. **Service-managed.** [commandclaw-memory](commandclaw-memory.md) owns the working clone and exposes a REST API. Agents talk to the memory service, never the wiki directly. Discipline at the boundary.

Both topologies produce the same artifact on disk and in git.

## Why this pattern over alternatives

| Alternative | Why we didn't |
|---|---|
| **RAG over raw/** | Re-derives synthesis every query. No compounding. Expensive at scale. |
| **Notion/Confluence** | Not git-native. Diff is manual. Export is second-class. |
| **Hand-maintained wiki** | Humans don't scale. The point is the LLM does the maintenance. |
| **Vector DB only** | Loses structure. Loses wikilinks. Loses the human-readable surface. |

The Karpathy pattern wins because the artifact is first-class for both LLMs (plain text, structured) and humans (markdown, Obsidian, git), and the compounding effect means query cost goes down over time, not up.

## Key documents

- [README](https://github.com/FnSK4R17s/commandclaw-wiki/blob/main/README.md) — getting started
- [CLAUDE.md](https://github.com/FnSK4R17s/commandclaw-wiki/blob/main/CLAUDE.md) — the schema the LLM follows
- [PRD.md](https://github.com/FnSK4R17s/commandclaw-wiki/blob/main/PRD.md) — the pattern document (Karpathy's original, adapted)
