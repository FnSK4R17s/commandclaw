# Stage 1 — Research

> Observation only. No design, no requirements, no solutions.

**Feature:** complete-tools-init
**One-liner:** Make agent/tools/__init__.py export all 12 tool factories consistently (currently lists 8, missing file_list, file_delete, browse_skills, install_skill).
**Date:** 2026-04-22

## Existing surface area

What modules, files, configs, and tests this feature will touch or depend on.
Cite concrete paths. Do not invent.

- `src/commandclaw/agent/tools/__init__.py` — package init; currently imports and re-exports 8 of the 12 factories; `__all__` lists exactly those 8
- `src/commandclaw/agent/tools/bash_tool.py` — exports `create_bash_tool` (in `__init__`)
- `src/commandclaw/agent/tools/file_read.py` — exports `create_file_read_tool` (in `__init__`); also exports private `_validate_vault_path` used by `file_write`, `file_delete`, `file_list`
- `src/commandclaw/agent/tools/file_write.py` — exports `create_file_write_tool` (in `__init__`)
- `src/commandclaw/agent/tools/file_delete.py` — exports `create_file_delete_tool` (NOT in `__init__`)
- `src/commandclaw/agent/tools/file_list.py` — exports `create_file_list_tool` (NOT in `__init__`)
- `src/commandclaw/agent/tools/vault_memory.py` — exports `create_memory_read_tool`, `create_memory_write_tool` (both in `__init__`)
- `src/commandclaw/agent/tools/vault_skill.py` — exports `create_list_skills_tool`, `create_read_skill_tool` (both in `__init__`)
- `src/commandclaw/agent/tools/skill_registry.py` — exports `create_browse_skills_tool`, `create_install_skill_tool` (NEITHER in `__init__`)
- `src/commandclaw/agent/tools/system_info.py` — exports `create_system_info_tool` (in `__init__`)
- `src/commandclaw/agent/graph.py` — primary caller; imports all 12 factories directly from submodules, never from the package
- `src/commandclaw/agent/runtime.py` — secondary caller; imports 10 of the 12 factories directly from submodules (omits `create_browse_skills_tool` and `create_install_skill_tool`); never from the package

## Relevant patterns already in the codebase

The 8 names currently in `__all__` are a verbatim list — no wildcard imports, no
`__init__`-level logic. The pattern to mirror is: one `from commandclaw.agent.tools.<submodule> import <factory>` line per factory, then name added to `__all__`. See `__init__.py` lines 5-21.

The two missing factories with no-`vault_path` signature are `create_browse_skills_tool()` and `create_install_skill_tool(vault_path)` in `skill_registry.py`. The signature difference (`create_browse_skills_tool` takes no arguments) is already present and valid — it is not an obstacle to re-export.

Both primary callers (`graph.py` ll. 239-256, `runtime.py` ll. 34-46) use the
submodule import style exclusively (lazy, inside a function body). Zero callsites
use `from commandclaw.agent.tools import <factory>`.

## Constraints discovered

- Python 3.11, `from __future__ import annotations` present in all submodules.
- Ruff rules `E,F,I,N,W,UP`, line-length 100; any new import lines in `__init__.py` must be `ruff`-clean (alphabetical import ordering is enforced by rule `I`).
- `__all__` must be kept in sync with the import lines — ruff `F401` would fire on unused imports if a name were added to imports but not `__all__`, and `F401` is included via rule `F`.
- `create_browse_skills_tool` takes no `vault_path` argument; `create_install_skill_tool` takes `vault_path: Path`. Both signatures are fine for re-export — callers already know the signatures.
- No circular import risk: `skill_registry.py` imports only stdlib + `langchain_core.tools`; `file_list.py` and `file_delete.py` only import from `file_read` (a private helper), not from `__init__`.

## qmd findings (if enabled)

No hits from `shikhar-wiki` at `minScore >= 0.3` are relevant to this feature.
Top result (`strongdm-software-factory.md`, score 0.88) is about AI-assisted
software development practices at StrongDM — unrelated to Python package
interface consistency. No guidance sourced from qmd.

## Unknowns surfaced

- Whether any external consumers (outside `src/commandclaw/`) or tests import
  from the package level (`from commandclaw.agent.tools import ...`). The grep
  covered `src/` only; test files and scripts were not scanned.
- Whether the incomplete `__all__` was intentional (e.g., `file_delete` and
  `file_list` were late additions and the `__init__` was never updated) or a
  deliberate omission. Current evidence points to accidental omission — both
  callers already use all 12 factories.
- `runtime.py` does not wire `create_browse_skills_tool` or
  `create_install_skill_tool` into the tools list at all (unlike `graph.py`
  which does). That divergence is out of scope here but may surface as a
  separate concern.
