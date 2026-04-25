# Command Claw — Agent Instructions

> Single source of agent conventions for this repo. `AGENTS.md` is a symlink to
> this file — both filenames resolve here.

## Project summary

Command Claw is a git-native AI agent platform where a vault repo is the control plane: agent configuration, memory, and behavior rules live as files you can inspect, edit, version, and audit. Python ≥3.11, packaged with hatchling. Source under [src/commandclaw/](src/commandclaw/), CLI entry `commandclaw = commandclaw.__main__:main`. Built on LangChain / LangGraph, python-telegram-bot, MCP. Agents are typically spawned in Docker via [scripts/spawn-agent.sh](scripts/spawn-agent.sh).

## Conventions

- **Formatting / linting:** `ruff` (config in [pyproject.toml](pyproject.toml), `target-version = "py311"`, `line-length = 100`, rules `E,F,I,N,W,UP`). Run `./.venv/bin/ruff check .` before commit.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, …). Subject ≤50 chars. Body explains *why*, not what — code already shows what.
- **Branches:** `main` is trunk. Feature work on `feat/<slug>`, fixes on `fix/<slug>`.
- **Tests:** `make test` (or `./.venv/bin/pytest`). Must pass before commit. Full guide in [TEST.md](TEST.md).
- **Python env:** Always use `./.venv/bin/<tool>`. Never call a global `pytest`, `ruff`, or `python` — they will miss project deps and produce misleading errors.
- **No emojis** in source files, commits, or docs unless explicitly requested.

## Testing

See [TEST.md](TEST.md) for the full guide.

Quick rules:
- Async tests use `asyncio_mode = "auto"`; write `async def test_*` directly, no decorator.
- Markers are strict (`--strict-markers`). Register any new `@pytest.mark.foo` under `[tool.pytest.ini_options].markers` in [pyproject.toml](pyproject.toml) before using it.
- TDD subagents `tdd-red`, `tdd-green`, `tdd-refactor` are installed under [.claude/agents/](.claude/agents/). Use them for one-test-at-a-time vertical slices.

### E2e tests and `.env.test`

E2e tests require **`.env.test`** (not `.env`). `.env` has Docker-internal hostnames (`gateway:8420`); `.env.test` has host-side URLs (`localhost:8420`) for running tests from the host machine. The `tests/e2e/conftest.py` loads `.env.test` automatically via `dotenv.load_dotenv()`.

- **Run e2e:** `make test-e2e` (sources `.env.test`, runs `pytest -m e2e -v`).
- **Run everything except e2e:** `make test-all`.
- **MCP tests** are marked `@pytest.mark.mcp` and excluded by default — they require a running MCP gateway at `localhost:8420`. Run with `pytest -m mcp`.
- **Never use `.env` for e2e tests.** It contains Docker-internal hostnames that won't resolve on the host.

## Anti-patterns

Read [ANTIPATTERNS.md](ANTIPATTERNS.md) before starting non-trivial work in this
repo. The file is append-only — newest entries first. Each entry describes a
mistake the agent has previously made and the correct approach.

When the user corrects you, append a new entry via:

```bash
${CLAUDE_SKILL_DIR}/scripts/log-antipattern.sh "<one-line summary>" "<correct approach>"
```

(Requires the `repo-best-practices` skill.)

## Repeated-task candidates

Tasks the user has requested multiple times that may warrant lifting into a
skill or subagent. When deferred, log here so the next session sees them.

<!-- Format: -->
<!-- - **<task name>** — requested <N> times. Last seen: <YYYY-MM-DD>. Notes: <…> -->
