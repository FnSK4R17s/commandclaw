# Stage 1 — Research

> Observation only. No design, no requirements, no solutions.

**Feature:** extract-vault-path-validator
**One-liner:** Move _validate_vault_path out of agent/tools/file_read.py into a shared agent/tools/_paths.py so siblings stop reaching through a private API.
**Date:** 2026-04-22

## Existing surface area

What modules, files, configs, and tests this feature will touch or depend on.
Cite concrete paths. Do not invent.

- `src/commandclaw/agent/tools/file_read.py` — defines `_validate_vault_path` at L15-24; also a direct caller at L34
- `src/commandclaw/agent/tools/file_write.py` — imports `_validate_vault_path` from `file_read` at L10; calls it at L22
- `src/commandclaw/agent/tools/file_delete.py` — imports `_validate_vault_path` from `file_read` at L10; calls it at L22
- `src/commandclaw/agent/tools/file_list.py` — imports `_validate_vault_path` from `file_read` at L10; calls it at L22
- `src/commandclaw/agent/tools/__init__.py` — re-exports tool factories; does not import `_validate_vault_path` directly; will not need changes unless `_paths` is added to `__all__`
- `src/commandclaw/agent/tools/bash_tool.py` — no path validation; uses `vault_path` only as `cwd` for subprocess; not a candidate
- `src/commandclaw/agent/tools/vault_memory.py` — no path validation; delegates entirely to `commandclaw.vault.memory` helpers; not a candidate
- `src/commandclaw/agent/tools/vault_skill.py` — no path validation; delegates entirely to `commandclaw.vault.skills`; not a candidate
- `src/commandclaw/agent/tools/skill_registry.py` — no vault-scoped path validation; clones to `/tmp`, copies into `vault_path / ".agents" / "skills" / skill_name` directly with `shutil.copytree`; not a candidate
- `src/commandclaw/agent/tools/system_info.py` — no filesystem path logic at all; not a candidate
- `tests/test_tools_files.py` — 54-line test file covering `file_read`, `file_write`, and path-escape rejection; imports `create_file_read_tool` and `create_file_write_tool` only; does NOT directly import or patch `_validate_vault_path`

## Relevant patterns already in the codebase

- All four file tools follow the same factory pattern (`create_<tool>_tool(vault_path: Path) -> BaseTool`) and capture `vault_path` via closure. The validator is called as the first operation inside each inner `@tool` function before any I/O.
- No existing shared utility module exists under `agent/tools/`. The only private-name convention seen is the leading underscore on `_validate_vault_path` and the local `_ensure_registry_cache` in `skill_registry.py` — both module-private helpers.
- `vault/` directory contains several modules (`memory.py`, `skills.py`, `workspace.py`, `git_ops.py`, etc.) but none contain any path-scoping or path-validation helpers. The vault layer deals with git ops, skill discovery, and memory reads/writes — not sandboxing.
- The `_validate_vault_path` signature is `(file_path: str, vault_path: Path) -> Path`. It resolves the path, checks `startswith(str(vault_resolved) + "/")` or exact equality, and raises `ValueError` if outside. This is the complete implementation; there is no second or alternate validator anywhere in the repo.

## Constraints discovered

- Python 3.11+; `pathlib.Path` is the standard path type throughout.
- `ruff` enforces `E,F,I,N,W,UP` with `line-length = 100` and `target-version = "py311"`. A new `_paths.py` module must comply; import sorting (`I`) means new imports in callers must be ordered correctly.
- `__init__.py` for `agent/tools` does not expose `_validate_vault_path` and should continue not to — the leading underscore convention must be preserved on the new home.
- Tests exercise the path-escape behavior through the tool factories (end-to-end), not by calling `_validate_vault_path` directly. No test patches the function; no monkeypatching of the import path is present. Updating the import location in callers will not break any existing test.
- `file_list.py` passes `directory` (not `file_path`) as the first argument — the parameter name differs, but the function accepts `str`, so the call is compatible.

## qmd findings (if enabled)

No relevant hits from `shikhar-wiki` or `shikhar-raw`. Both keyword and vector searches returned only unrelated template pages and Nepal geography content (scores 52-59%, below the relevance threshold). No prior art or wiki guidance on private-module extraction applies here.

## Unknowns surfaced

- Whether `_paths.py` should be added to `agent/tools/__init__.py` `__all__` (exposing it as semi-public) or kept entirely private (underscore prefix, no `__all__` entry). Convention here leans toward keeping it private, but the intended audience (just these four siblings vs. possible future consumers outside the package) is unclear.
- Whether the boundary check logic (`startswith(str(vault_resolved) + "/") and resolved != vault_resolved`) has any known edge cases on Windows-style paths or symlinks inside the vault. The codebase targets Linux/Docker (WSL2 confirmed by env), so this is low risk, but worth documenting in requirements.
- `file_list.py` calls `_validate_vault_path(directory, vault_path)` where `directory` defaults to `"."`. A call with `"."` resolves to `vault_resolved` itself. The exact equality branch (`resolved == vault_resolved`) in the validator permits this, but it is worth confirming this case has a test — currently no test exercises the vault-root listing path in `test_tools_files.py`.
- `__init__.py` does not export `create_file_delete_tool` or `create_file_list_tool` — those factories are used elsewhere but not re-exported from the package. This is a pre-existing gap unrelated to this refactor but worth noting in case test coverage is added.
