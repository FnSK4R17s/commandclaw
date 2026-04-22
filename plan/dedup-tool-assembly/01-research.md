# Stage 1 — Research

> Observation only. No design, no requirements, no solutions.

**Feature:** dedup-tool-assembly
**One-liner:** Extract the 12-tool assembly list into a single build_default_tools helper so runtime.py and graph.py both use it.
**Date:** 2026-04-22

## Existing surface area

Files this feature will touch or depend on.

- `src/commandclaw/agent/runtime.py` — `create_agent()`, lines 34–92: imports 9 factories inline, assembles 10 native tools, then appends MCP tools eagerly (connect + await at startup).
- `src/commandclaw/agent/graph.py` — `create_agent_graph()` (or equivalent), lines 238–295: imports 11 factories inline, assembles 12 native tools, then sets up MCP tools lazily (connected on first invocation via a double-checked lock).
- `src/commandclaw/agent/tools/__init__.py` — current public surface: exports 8 of the 12 factories (missing `file_delete`, `file_list`, `create_browse_skills_tool`, `create_install_skill_tool`).
- `src/commandclaw/agent/tools/bash_tool.py` — `create_bash_tool(vault_path, timeout)`: takes `vault_path` + `timeout`.
- `src/commandclaw/agent/tools/file_read.py` — `create_file_read_tool(vault_path)`: also houses `_validate_vault_path` shared by file_list and file_delete.
- `src/commandclaw/agent/tools/file_write.py` — `create_file_write_tool(vault_path)`.
- `src/commandclaw/agent/tools/file_delete.py` — `create_file_delete_tool(vault_path)`.
- `src/commandclaw/agent/tools/file_list.py` — `create_file_list_tool(vault_path)`.
- `src/commandclaw/agent/tools/vault_memory.py` — `create_memory_read_tool(vault_path)`, `create_memory_write_tool(vault_path, repo)`: the write tool takes `repo: VaultRepo` as a second argument — the only factory that does this.
- `src/commandclaw/agent/tools/vault_skill.py` — `create_list_skills_tool(vault_path)`, `create_read_skill_tool(vault_path)`.
- `src/commandclaw/agent/tools/skill_registry.py` — `create_browse_skills_tool()` (no args), `create_install_skill_tool(vault_path)`.
- `src/commandclaw/agent/tools/system_info.py` — `create_system_info_tool()` (no args): async inner tool, uses `os.environ` directly.
- `src/commandclaw/config.py` — `Settings` (pydantic-settings): relevant fields are `vault_path: Path | None`, `bash_timeout: int` (default 120), `mcp_gateway_url: str | None`, `mcp_agent_key: str | None`, `agent_id: str`.
- `src/commandclaw/vault/git_ops.py` — `VaultRepo` class, needed by `create_memory_write_tool`.
- `tests/test_tools_bash.py` — imports `create_bash_tool` directly; no patching of the assembled list.
- `tests/test_tools_files.py` — imports `create_file_read_tool`, `create_file_write_tool` directly; no patching of the assembled list.
- `tests/test_vault_config_identity.py` — no tool-list references.
- `tests/test_agent_retry.py` — imports `AgentResult` from `runtime`; no tool-list references.

## Relevant patterns already in the codebase

1. **Factory pattern for every tool.** Each tool module exposes one or more `create_*_tool(...)` functions returning a `BaseTool`. The caller owns instantiation; there is no module-level singleton. A `build_default_tools` helper should follow the same pattern.

2. **`tools/__init__.py` as the public re-export surface.** The file already re-exports 8 of the 12 factories. Precedent: add the helper to this same file and expand `__all__`.

3. **VaultRepo constructed inside the caller before tools are built.** Both `runtime.py` (line 55) and `graph.py` (line 260) call `VaultRepo(vault_path)` and `repo.ensure_repo()` before building tools. The `create_memory_write_tool` factory needs `repo`; so `build_default_tools` will receive either `(settings, vault_path, repo)` or `(settings, vault_path)` with repo construction happening inside — this is a design question, not resolved here.

4. **Lazy vs. eager MCP loading is NOT part of the native tool list.** In both files, MCP tools are appended to the `tools` list *after* the native list is assembled. The two call sites differ in *how* MCP is loaded (see Constraints), but the native block is the shared surface.

5. **Inline imports inside async functions.** Both files use deferred `from commandclaw.agent.tools.X import Y` inside the function body (not at module top level). The current `tools/__init__.py` uses top-level imports. Any new helper should be consistent with whichever style the design chooses.

## Constraints discovered

### Tool-list differences between runtime.py and graph.py

| # | Tool | runtime.py (10 tools) | graph.py (12 tools) |
|---|------|-----------------------|---------------------|
| 1 | bash | `create_bash_tool(vault_path, timeout=settings.bash_timeout)` | same |
| 2 | file_list | `create_file_list_tool(vault_path)` | same |
| 3 | file_read | `create_file_read_tool(vault_path)` | same |
| 4 | file_write | `create_file_write_tool(vault_path)` | same |
| 5 | file_delete | `create_file_delete_tool(vault_path)` | same |
| 6 | memory_read | `create_memory_read_tool(vault_path)` | same |
| 7 | memory_write | `create_memory_write_tool(vault_path, repo)` | same |
| 8 | list_skills | `create_list_skills_tool(vault_path)` | same |
| 9 | read_skill | `create_read_skill_tool(vault_path)` | same |
| 10 | browse_skills | **ABSENT** | `create_browse_skills_tool()` |
| 11 | install_skill | **ABSENT** | `create_install_skill_tool(vault_path)` |
| 12 | system_info | `create_system_info_tool()` | `create_system_info_tool()` |

Summary of differences:
- `graph.py` has 2 extra tools: `browse_skills` and `install_skill` (from `skill_registry.py`). `runtime.py` does not include these.
- Order is otherwise identical between the two files.

### MCP handling differs significantly

- **runtime.py** (eager): connects the MCP client and awaits `create_mcp_tools()` at `create_agent()` startup. Uses `settings.mcp_agent_key` (checked alongside `settings.mcp_gateway_url`). Disconnects in `cleanup()`.
- **graph.py** (lazy): creates the `MCPClient` object at graph-build time but defers `connect()` + `create_mcp_tools()` to the first `run_agent()` invocation, protected by a `asyncio.Lock()` double-checked pattern. Only checks `settings.mcp_gateway_url` (not `mcp_agent_key`) as the gate. Also passes `agent_id` to `MCPClient` constructor; `runtime.py` does not.

MCP is NOT part of the native tool list and should remain outside any `build_default_tools` helper.

### Other constraints

- Python 3.11, ruff rules E,F,I,N,W,UP, line-length 100.
- `create_memory_write_tool` is the only factory that takes a `VaultRepo` argument. A helper signature must account for this — either constructing `repo` internally or accepting it as a parameter.
- `system_info` uses `async def` inside its factory (no parameters); `bash` uses `timeout` from `settings.bash_timeout`. These are the only non-`vault_path` inputs among the native tools.
- `Settings.vault_path` is typed `Path | None`; callers resolve it before use (via workspace manager). The helper should receive an already-resolved `Path`, not `settings` directly, or handle the `None` case.
- `tools/__init__.py` currently omits `create_file_delete_tool`, `create_file_list_tool`, `create_browse_skills_tool`, and `create_install_skill_tool` from its exports.

## qmd findings

Queries run against `shikhar-wiki` collection:
- `{type: 'lex', query: 'DRY helper function module interface'}`
- `{type: 'vec', query: 'eliminating duplicated setup logic across call sites'}`

Results (min score 0.5): two hits returned — `shikhar-wiki/log.md` (score 0.88, append-only ingestion log) and `shikhar-wiki/index.md` (score 0.50, wiki index). Neither is relevant to this feature. No hits from `shikhar-raw`. As expected: no prior art in the personal wiki for this pattern.

## Unknowns surfaced

1. **Should the 2-tool discrepancy (`browse_skills`, `install_skill`) be resolved before extracting the helper?** The helper could either always include all 12 tools (making `runtime.py` gain 2 new tools) or accept a flag/parameter to vary the set. The intent of the discrepancy is not documented in either file.

2. **Should `build_default_tools` construct the `VaultRepo` internally or require the caller to pass it?** Both call sites construct `repo` before building tools, but `runtime.py` also uses `repo` for vault health checks (`recover_vault`). If `repo` construction moves inside the helper, `runtime.py` loses its handle.

3. **Should MCP setup (eager vs. lazy) be unified at the same time, or is it out of scope for this refactor?** The two strategies are materially different and may be intentional.

4. **Are there any other callers of the tool factories outside `runtime.py` and `graph.py`?** A broader grep for `create_bash_tool`, `create_file_read_tool`, etc. across the repo (beyond tests) was not run.

5. **Is `tools/__init__.py` intended to be the definitive re-export surface, or are inline imports inside async functions a deliberate encapsulation choice?** Expanding `__init__.py` affects what is importable at module load time.
