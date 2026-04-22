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
| [inject-nemo-api-key](inject-nemo-api-key/) | [✅](inject-nemo-api-key/01-research.md) | [⏳](inject-nemo-api-key/02-requirements.md) | [⏳](inject-nemo-api-key/03-deep-research.md) | [⏳](inject-nemo-api-key/04-backlog-item.md) | draft |
| [runtime-max-tokens-default](runtime-max-tokens-default/) | [✅](runtime-max-tokens-default/01-research.md) | [⏳](runtime-max-tokens-default/02-requirements.md) | [⏳](runtime-max-tokens-default/03-deep-research.md) | [⏳](runtime-max-tokens-default/04-backlog-item.md) | draft |
| [close-runtime-span-on-exception](close-runtime-span-on-exception/) | [✅](close-runtime-span-on-exception/01-research.md) | [⏳](close-runtime-span-on-exception/02-requirements.md) | [⏳](close-runtime-span-on-exception/03-deep-research.md) | [⏳](close-runtime-span-on-exception/04-backlog-item.md) | draft |
| [split-agent-graph](split-agent-graph/) | [✅](split-agent-graph/01-research.md) | [⏳](split-agent-graph/02-requirements.md) | [⏳](split-agent-graph/03-deep-research.md) | [⏳](split-agent-graph/04-backlog-item.md) | draft |
| [unify-agent-entry](unify-agent-entry/) | [✅](unify-agent-entry/01-research.md) | [⏳](unify-agent-entry/02-requirements.md) | [⏳](unify-agent-entry/03-deep-research.md) | [⏳](unify-agent-entry/04-backlog-item.md) | draft |
| [dedup-tool-assembly](dedup-tool-assembly/) | [✅](dedup-tool-assembly/01-research.md) | [⏳](dedup-tool-assembly/02-requirements.md) | [⏳](dedup-tool-assembly/03-deep-research.md) | [⏳](dedup-tool-assembly/04-backlog-item.md) | draft |
| [vault-facade-to-class](vault-facade-to-class/) | [✅](vault-facade-to-class/01-research.md) | [⏳](vault-facade-to-class/02-requirements.md) | [⏳](vault-facade-to-class/03-deep-research.md) | [⏳](vault-facade-to-class/04-backlog-item.md) | draft |
| [tracing-span-helper](tracing-span-helper/) | [✅](tracing-span-helper/01-research.md) | [⏳](tracing-span-helper/02-requirements.md) | [⏳](tracing-span-helper/03-deep-research.md) | [⏳](tracing-span-helper/04-backlog-item.md) | draft |
| [extract-vault-path-validator](extract-vault-path-validator/) | [✅](extract-vault-path-validator/01-research.md) | [⏳](extract-vault-path-validator/02-requirements.md) | [⏳](extract-vault-path-validator/03-deep-research.md) | [⏳](extract-vault-path-validator/04-backlog-item.md) | draft |
| [model-token-table](model-token-table/) | [✅](model-token-table/01-research.md) | [⏳](model-token-table/02-requirements.md) | [⏳](model-token-table/03-deep-research.md) | [⏳](model-token-table/04-backlog-item.md) | draft |
| [complete-tools-init](complete-tools-init/) | [✅](complete-tools-init/01-research.md) | [⏳](complete-tools-init/02-requirements.md) | [⏳](complete-tools-init/03-deep-research.md) | [⏳](complete-tools-init/04-backlog-item.md) | draft |
| [mcp-package-interface](mcp-package-interface/) | [✅](mcp-package-interface/01-research.md) | [⏳](mcp-package-interface/02-requirements.md) | [⏳](mcp-package-interface/03-deep-research.md) | [⏳](mcp-package-interface/04-backlog-item.md) | draft |

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
- **Status column** is freeform text, not a link. It is the shipping state,
  not the planning state. A feature can be `✅` across all stages and still
  be `draft` until someone commits to building it. Typical values:
  `draft`, `v1 ready`, `v1 done`, `v2 done`, `archived`.

## Files per feature

Each `plan/<slug>/` folder contains:

- `01-research.md` — what exists in the codebase today
- `02-requirements.md` — user-facing contract, acceptance criteria
- `03-deep-research.md` — resolved open questions, risks
- `04-backlog-item.md` — handoff document for an implementing agent
