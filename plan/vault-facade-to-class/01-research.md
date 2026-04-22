# Stage 1 — Research

> Observation only. No design, no requirements, no solutions.

**Feature:** vault-facade-to-class
**One-liner:** Replace the 14-name flat facade in vault/__init__.py with a single Vault class that exposes identity, memory, skills, and git as attributes.
**Date:** 2026-04-22

---

## Existing surface area

Files this feature will touch or depend on:

- `src/commandclaw/vault/__init__.py` — 15-name flat re-export facade (the replacement target)
- `src/commandclaw/vault/git_ops.py` — `VaultRepo` class; candidate for `Vault.git`
- `src/commandclaw/vault/memory.py` — 4 functions all taking `vault_path`; candidates for `Vault.memory.*`
- `src/commandclaw/vault/identity.py` — `Identity`, `VaultIdentity`, `load_identity`; candidate for `Vault.identity`
- `src/commandclaw/vault/skills.py` — `Skill`, `discover_skills`, `load_skill`; candidates for `Vault.skills.*`
- `src/commandclaw/vault/agent_config.py` — `AgentConfig`, `load_agent_config`; candidate for `Vault.config`
- `src/commandclaw/vault/recovery.py` — `check_vault_health`, `recover_vault`; candidates for `Vault.health()` / `Vault.recover()`
- `src/commandclaw/vault/workspace.py` — factory helpers; NOT in facade; callers import sub-module directly
- `src/commandclaw/agent/runtime.py` — imports `VaultRepo`, `check_vault_health`, `recover_vault`, `load_agent_config`, `load_identity`, `read_daily_notes`, `read_long_term_memory`, `discover_skills` (all direct sub-module imports)
- `src/commandclaw/agent/graph.py` — imports only `VaultRepo` from vault; reads vault files directly via `Path.read_text` (bypasses all vault functions for identity/config)
- `src/commandclaw/agent/tools/vault_memory.py` — imports `VaultRepo`, `read_daily_notes`, `read_long_term_memory`, `write_daily_note`
- `src/commandclaw/agent/tools/vault_skill.py` — imports `discover_skills`, `load_skill`
- `src/commandclaw/agent/prompt.py` — imports `AgentConfig`, `VaultIdentity`, `Skill` as type annotations only
- `src/commandclaw/__main__.py` — imports `create_workspace` directly from `commandclaw.vault.workspace`
- `tests/test_vault_git_ops.py` — tests `VaultRepo` directly
- `tests/test_vault_memory.py` — tests all 4 memory functions directly
- `tests/test_vault_skills.py` — tests `discover_skills`, `load_skill`, `check_vault_health`, `recover_vault` directly
- `tests/test_vault_config_identity.py` — tests `AgentConfig`, `load_agent_config`, `Identity`, `VaultIdentity`, `load_identity`, and the private `_parse_identity_md`

---

## Facade inventory

`vault/__init__.py` `__all__` — 15 names (the one-liner said "14" but the actual `__all__` contains 15):

| # | Name | Origin | Kind |
|---|------|---------|------|
| 1 | `AgentConfig` | `agent_config` | dataclass |
| 2 | `Identity` | `identity` | dataclass |
| 3 | `Skill` | `skills` | dataclass |
| 4 | `VaultIdentity` | `identity` | dataclass |
| 5 | `VaultRepo` | `git_ops` | class |
| 6 | `check_vault_health` | `recovery` | function |
| 7 | `discover_skills` | `skills` | function |
| 8 | `load_agent_config` | `agent_config` | function |
| 9 | `load_identity` | `identity` | function |
| 10 | `load_skill` | `skills` | function |
| 11 | `read_daily_notes` | `memory` | function |
| 12 | `read_long_term_memory` | `memory` | function |
| 13 | `recover_vault` | `recovery` | function |
| 14 | `update_long_term_memory` | `memory` | function |
| 15 | `write_daily_note` | `memory` | function |

---

## Caller map (critical)

Every caller uses direct sub-module imports. No caller uses `from commandclaw.vault import <name>` — the top-level facade is currently dead code.

| Name | Production callers | Test callers |
|------|--------------------|--------------|
| `VaultRepo` | `agent/runtime.py:50`, `agent/graph.py:257`, `agent/tools/vault_memory.py:10` | `test_vault_git_ops.py`, `test_vault_memory.py`, `test_vault_skills.py` |
| `check_vault_health` | `agent/runtime.py:51` | `test_vault_skills.py` |
| `recover_vault` | `agent/runtime.py:51` | `test_vault_skills.py` |
| `load_agent_config` | `agent/runtime.py:144` | `test_vault_config_identity.py` |
| `load_identity` | `agent/runtime.py:145` | `test_vault_config_identity.py` |
| `read_long_term_memory` | `agent/runtime.py:146`, `agent/tools/vault_memory.py:11` | `test_vault_memory.py` |
| `read_daily_notes` | `agent/runtime.py:146`, `agent/tools/vault_memory.py:11` | `test_vault_memory.py` |
| `write_daily_note` | `agent/tools/vault_memory.py:11` | `test_vault_memory.py` |
| `discover_skills` | `agent/runtime.py:147`, `agent/tools/vault_skill.py:10` | `test_vault_skills.py` |
| `load_skill` | `agent/tools/vault_skill.py:10` | `test_vault_skills.py` |
| `AgentConfig` | `agent/prompt.py:5` (type annotation only) | `test_vault_config_identity.py` |
| `VaultIdentity` | `agent/prompt.py:6` (type annotation only) | `test_vault_config_identity.py` |
| `Skill` | `agent/prompt.py:7` (type annotation only) | `test_vault_skills.py` |
| `update_long_term_memory` | none | `test_vault_memory.py` |
| `Identity` | none | `test_vault_config_identity.py` |
| `create_workspace` | `__main__.py:47` (direct sub-module, not in facade) | none |

---

## Relevant patterns already in the codebase

**Uniform `vault_path: Path` first argument.** Every vault function uses `vault_path: Path` as its first parameter. This is the natural candidate for `self.path` in a `Vault` class — all current call sites would collapse `f(self.path, ...)` to `self.f(...)`.

**`VaultRepo` already bundles path + git state.** `VaultRepo.__init__(path)` stores `self.path` and `self.repo`. It is a well-scoped "sub-object" pattern already. It is a natural fit for `Vault.git: VaultRepo`.

**Write functions carry dual signature.** `write_daily_note(vault_path, entry, repo)` and `update_long_term_memory(vault_path, section, entry, repo)` take both the path and the repo object. If `Vault` owns both, these signatures reduce to `(entry)` and `(section, entry)`.

**`agent/runtime.py:invoke_agent` loads all vault state at invocation time.** Five separate calls (`load_agent_config`, `load_identity`, `read_long_term_memory`, `read_daily_notes`, `discover_skills`) all pass the same `vault_path`. This is the primary hot path driving the refactor motivation.

**`agent/graph.py` has a local `load_identity` graph node** that shadows the vault function name. It reads vault files by raw `Path.read_text` instead of using the vault module. This is an independent reimplementation, not a consumer of the vault API.

**All tests import from direct sub-modules, not from the facade.** The test suite already bypasses `vault/__init__.py`. Tests will need updating only if sub-module interfaces change.

---

## Constraints discovered

- Python 3.11+. Dataclasses and `from __future__ import annotations` are used throughout.
- Ruff config: `target-version = "py311"`, `line-length = 100`, rules `E,F,I,N,W,UP`.
- `asyncio_mode = "auto"` in pytest — async tests need no decorator.
- Strict markers in pytest — any new `@pytest.mark.foo` must be registered in `pyproject.toml`.
- `test_vault_config_identity.py` imports `_parse_identity_md` (private function) directly. Any refactor must not move or rename this without updating that test.
- `VaultRepo` is used as a passed-in collaborator by `memory.py` and `recovery.py`; those modules import `VaultRepo` directly at the top of the file. A `Vault` class that owns a `VaultRepo` would need to resolve circular import risk (`vault/__init__.py` imports from sub-modules that import from each other).
- `workspace.py` is intentionally excluded from the facade. The feature brief does not include it. Its callers (`__main__.py`) import the sub-module directly and are unaffected.
- `agent/prompt.py` imports `AgentConfig`, `VaultIdentity`, and `Skill` as type annotations. These data classes must remain importable from their sub-modules or a compatibility re-export.

---

## qmd findings

Collections searched: `shikhar-wiki`, `shikhar-raw`.
Queries run: `{type: lex, query: "facade class attribute composition"}` and `{type: vec, query: "deep module with small interface hiding implementation"}`.
Intent: consolidating flat exports into a class with sub-attributes.

No relevant hits. The two returned results (score 0.88 "Agentic Coding", score 0.50 StrongDM article) are unrelated to the refactor pattern. No wiki content applies.

---

## Unknowns surfaced

1. **Circular import risk.** `memory.py` and `recovery.py` both `from commandclaw.vault.git_ops import VaultRepo` at module level. If `vault/__init__.py` defines a `Vault` class that instantiates these, the import order must be verified — or the class definition must use deferred imports.

2. **`agent/graph.py` divergence.** The graph reads vault files directly without using any vault functions for identity/config. Is this intentional (performance, avoiding overhead) or accidental drift? The refactor scope should clarify whether `graph.py` is also brought in-line.

3. **`update_long_term_memory` has no production caller.** It is exported but only tested. Is it intentionally dormant, deprecated, or simply not yet wired up?

4. **Backward-compatibility requirement.** Since no caller uses `from commandclaw.vault import <name>` today, the question is whether the sub-module paths (`commandclaw.vault.memory`, etc.) must stay stable for external consumers or if they can also change.

5. **Data class ownership.** `AgentConfig`, `Identity`, `VaultIdentity`, and `Skill` are used as type annotations in `agent/prompt.py` and as return types of vault functions. If they are wrapped inside the `Vault` class namespace, import paths for callers change.

6. **`workspace.py` relationship.** The feature brief excludes `workspace.py`. Should `Vault` be constructable via `Vault.from_workspace(agent_id)` as a factory, or does that belong elsewhere?
