# Stage 1 — Research

> Observation only. No design, no requirements, no solutions.

**Feature:** mcp-package-interface
**One-liner:** Add re-exports of MCPClient, MCPGatewayUnavailable, MCPAgentNotEnrolled, and MCPToolDef to mcp/__init__.py.
**Date:** 2026-04-22

## Existing surface area

What modules, files, configs, and tests this feature will touch or depend on.

- `src/commandclaw/mcp/__init__.py` — currently contains only one docstring line; the write target for re-exports.
- `src/commandclaw/mcp/client.py` — defines all four target names plus `GatewaySession`; also contains private helpers `_parse_sse_response`, `_extract_text`, `_MCP_HEADERS`, `_TIMEOUT`.
- `src/commandclaw/mcp/tools.py` — defines `create_mcp_tools` (public, async) and private helpers `_build_input_model`, `_wrap_tool`, `_JSON_TYPE_MAP`; imports `MCPClient` and `MCPToolDef` from `commandclaw.mcp.client`.
- `src/commandclaw/agent/graph.py` — caller; lazy-imports `MCPClient` from `commandclaw.mcp.client` and `create_mcp_tools` from `commandclaw.mcp.tools`; also imports the `client` submodule as `_mcp_client_module` to access exceptions by attribute (`_mcp_client_module.MCPGatewayUnavailable`, `_mcp_client_module.MCPAgentNotEnrolled`).
- `src/commandclaw/agent/runtime.py` — caller; lazy-imports `MCPClient` from `commandclaw.mcp.client` and `create_mcp_tools` from `commandclaw.mcp.tools`.
- `src/commandclaw/config.py` — defines `mcp_gateway_url` and `mcp_agent_key` settings fields; references MCP only via config, not imports.
- `src/commandclaw/agent/tools/system_info.py` — reads `COMMANDCLAW_MCP_GATEWAY_URL` env var directly via `os.environ`; does not import from `commandclaw.mcp`.

No tests currently import from `commandclaw.mcp.*`.

## Relevant patterns already in the codebase

**Public names in `mcp/client.py` (all classes, no `__all__` defined):**

| Name | Kind | Notes |
|---|---|---|
| `MCPGatewayUnavailable` | Exception class (ConnectionError) | Public; one of the four target re-exports |
| `MCPAgentNotEnrolled` | Exception class (PermissionError) | Public; one of the four target re-exports |
| `MCPToolDef` | Dataclass | Public; one of the four target re-exports |
| `GatewaySession` | Dataclass | Public by name; not listed as a re-export target but used internally |
| `MCPClient` | Dataclass with async context manager | Public; one of the four target re-exports |

**Public names in `mcp/tools.py`:**

| Name | Kind | Notes |
|---|---|---|
| `create_mcp_tools` | Async function | Public; the sole intended external API of this module |

**No `__all__` is defined in any `mcp/` file.** Callers can currently reach any name by direct submodule import.

**Caller import pattern — current (all lazy, inside `if` blocks or function bodies):**

```python
# graph.py lines 283-284 — imports submodule as alias to use exceptions
from commandclaw.mcp import client as _mcp_client_module
from commandclaw.mcp.client import MCPClient

# graph.py line 316 — deeper in the lazy-load block
from commandclaw.mcp.tools import create_mcp_tools

# runtime.py lines 48-49 — inside a function
from commandclaw.mcp.client import MCPClient
from commandclaw.mcp.tools import create_mcp_tools
```

**Notable detail in `graph.py`:** `MCPGatewayUnavailable` and `MCPAgentNotEnrolled` are accessed via the module alias (`_mcp_client_module.MCPGatewayUnavailable`) rather than direct name imports. This is the one import that cannot be trivially replaced with a `commandclaw.mcp` package-level import without also updating the call site.

## Constraints discovered

- **Python version:** 3.11+ (pyproject.toml `target-version = "py311"`). No compatibility constraints that affect simple re-exports.
- **No `__all__` discipline:** Neither `client.py` nor `tools.py` defines `__all__`, so there is no existing gate on what is "public". Adding re-exports to `__init__.py` is the first step toward defining that boundary.
- **`GatewaySession` scope:** `GatewaySession` is used internally by `MCPClient._bootstrap_session` and returned as `MCPClient._gateway_session`. It is technically public (no underscore prefix) but is not listed as a re-export target in the feature spec. The dataclass is only ever constructed inside `client.py`, so it need not be part of the initial `__init__.py` surface.
- **Lazy import pattern:** Both callers use lazy imports (inside function bodies / `if` blocks) to avoid circular imports at module load time. A re-export in `__init__.py` that imports from the submodules eagerly could in theory change import-time behaviour, but since `mcp/__init__.py` is currently near-empty (one docstring), no circular dependency exists today.
- **`create_mcp_tools` not in spec:** The feature spec lists four names from `client.py` only. `create_mcp_tools` from `tools.py` is not a target re-export. Both callers still import it directly from `commandclaw.mcp.tools`.
- **Lint rules:** `ruff` with `E,F,I,N,W,UP`. An `__init__.py` with bare re-export lines will pass cleanly; `F401` (imported but unused) would fire unless re-exported names appear in `__all__` or are used, so `__all__` must be declared.
- **No test coverage:** There are zero test files for `commandclaw.mcp.*`. Any implementation will need new tests.

## qmd findings

Both searches (`lex: package __init__.py re-export public api`, `vec: designing a small public interface for a module`) against `shikhar-wiki` returned no relevant hits. Top results were wiki templates and unrelated concept pages. No prior art in the personal knowledge base.

## Caller map (complete)

| Importer | Line(s) | Imported name(s) | Source module |
|---|---|---|---|
| `src/commandclaw/agent/graph.py` | 283 | `client` (as `_mcp_client_module`) | `commandclaw.mcp` (package) |
| `src/commandclaw/agent/graph.py` | 284 | `MCPClient` | `commandclaw.mcp.client` |
| `src/commandclaw/agent/graph.py` | 316 | `create_mcp_tools` | `commandclaw.mcp.tools` |
| `src/commandclaw/agent/graph.py` | 324–325 | `MCPGatewayUnavailable`, `MCPAgentNotEnrolled` | via `_mcp_client_module` attribute access |
| `src/commandclaw/agent/runtime.py` | 48 | `MCPClient` | `commandclaw.mcp.client` |
| `src/commandclaw/agent/runtime.py` | 49 | `create_mcp_tools` | `commandclaw.mcp.tools` |
| `src/commandclaw/mcp/tools.py` | 11 | `MCPClient`, `MCPToolDef` | `commandclaw.mcp.client` |

External scripts (`scripts/`): none import from `commandclaw.mcp`.
Tests: none import from `commandclaw.mcp.*`.

## Unknowns surfaced

- Should `GatewaySession` be included in the `__init__.py` re-exports, or intentionally left private? It is public by name convention but excluded from the spec.
- Should `create_mcp_tools` from `tools.py` eventually be promoted to the package surface too, or is the split between `client` and `tools` sub-surfaces intentional?
- After adding the re-exports, should existing callers (`graph.py`, `runtime.py`) be migrated to import from `commandclaw.mcp` instead of the submodules? The spec says add re-exports, not migrate callers — but this is a follow-on decision.
- The `graph.py` alias pattern (`from commandclaw.mcp import client as _mcp_client_module`) is used specifically to catch exceptions without importing them by name first. If the exceptions are re-exported at package level, this pattern could be simplified — but that is a caller-migration question outside Stage 1.
- No tests exist for `mcp/client.py` or `mcp/tools.py`. Should test coverage be a prerequisite for this change or a parallel track?
