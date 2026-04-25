# PLAN — Feature Planning Index

This file is the index for every planned feature in this repo. It is
maintained by the `plan-feature` skill. Every cell is a link — click through
to read the feature folder or the specific stage file. Sort rows by
most-recently-touched first. Do not hand-edit unless you know why.

## Features

> 💡 **Tip:** The ⏳ / 🚧 / ✅ glyphs in the table are **clickable links** —
> click any glyph to open that stage file. The feature name links to the
> feature folder.

| Feature | Research | Requirements | Deep Research | Backlog | Status |
|---------|----------|--------------|---------------|---------|--------|
| [message-queue](message-queue/) | [✅](message-queue/01-research.md) | [✅](message-queue/02-requirements.md) | [✅](message-queue/03-deep-research.md) | [✅](message-queue/04-backlog-item.md) | v1-ready |

<!--
Example row once features exist:

| [user-sso](user-sso/) | [✅](user-sso/01-research.md) | [🚧](user-sso/02-requirements.md) | [⏳](user-sso/03-deep-research.md) | [⏳](user-sso/04-backlog-item.md) | draft |
-->

## Conventions

- **Feature column** links to the feature folder: `[<slug>](<slug>/)`.
- **Stage cells** are links to the stage file, with the status glyph as the
  link text: `[<glyph>](<slug>/0N-stage-name.md)`.
  - `⏳` not started (file exists from template, empty scaffold)
  - `🚧` in progress
  - `✅` done
- **Status column** is an enum (set by `.planconfig`): one of
  `draft`, `v1-ready`, `v1-done`, `archived`.

## Files per feature

Each `plan/<slug>/` folder contains:

- `01-research.md` — what exists in the codebase today
- `02-requirements.md` — user-facing contract, acceptance criteria
- `03-deep-research.md` — resolved open questions, risks
- `04-backlog-item.md` — handoff document for an implementing agent
