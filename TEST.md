# Testing

Testing guide for Command Claw. Stack: **pytest 8** + **pytest-asyncio** + **pytest-cov**.

## Setup

Dev deps live in `[project.optional-dependencies].dev` in [pyproject.toml](pyproject.toml). Install into the project venv:

```bash
python3 -m venv .venv
./.venv/bin/pip install -e '.[dev]'
```

A pre-built `.venv/` already ships in this repo for convenience. Recreate it any time deps drift.

> **Important**: do not run `pytest` from your global `$PATH`. Use `./.venv/bin/pytest` or the `make` targets below. A system pytest will silently miss project deps (e.g. `gitpython`, `pytest-asyncio`) and report misleading import errors.

## Running tests

```bash
make test          # full suite via .venv/bin/pytest
make test-cov      # with coverage report (term-missing)
```

Direct invocation:

```bash
./.venv/bin/pytest                              # all tests
./.venv/bin/pytest tests/test_vault_memory.py   # single file
./.venv/bin/pytest -k "memory and write"        # by keyword
./.venv/bin/pytest -x --ff                      # stop on first fail, run failed-first
./.venv/bin/pytest -vv -s                       # verbose + show prints
```

## Configuration

All pytest config lives in [pyproject.toml](pyproject.toml) under `[tool.pytest.ini_options]`:

| Option | Value | Why |
|---|---|---|
| `testpaths` | `["tests"]` | Restrict collection to the `tests/` dir |
| `asyncio_mode` | `"auto"` | `async def test_*` runs without `@pytest.mark.asyncio` |
| `addopts` | `-ra --strict-markers --strict-config` | Show short summary for skips/xfails; reject typo'd markers and unknown config keys |

`--strict-markers` means any `@pytest.mark.foo` must first be registered. Add new markers under `markers = [...]` in the same config block.

## Writing new tests

- File names: `tests/test_*.py`. Class names: `Test*`. Function names: `test_*`.
- Async tests: just write `async def test_foo():` — no decorator needed (`asyncio_mode = "auto"`).
- Use `tmp_path` fixture for filesystem tests. Vault git-ops tests use `git.Repo.init(tmp_path)` — see [tests/test_vault_git_ops.py](tests/test_vault_git_ops.py) as the reference pattern.
- Test behavior through public interfaces. Avoid mocking internal collaborators. See `~/.claude/skills/tdd/references/tests.md` for the full philosophy.

## Coverage

```bash
make test-cov
```

Reports missing lines per module. To generate HTML:

```bash
./.venv/bin/pytest --cov=commandclaw --cov-report=html
open htmlcov/index.html
```

## TDD workflow

This repo has the [TDD skill](https://github.com/mattpocock/skills/tree/main/tdd) bootstrapped at [.claude/agents/](.claude/agents/) — three subagents (`tdd-red`, `tdd-green`, `tdd-refactor`) drive one-test-at-a-time vertical slices. Spawn them in sequence; audit each phase against the skill's `REWARD_HACKING.md` before accepting.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'git'` | Wrong pytest binary | Use `./.venv/bin/pytest` |
| `Unknown config option: asyncio_mode` warning | pytest-asyncio not installed in active env | Reinstall dev deps into `.venv` |
| `'foo' not found in markers configuration option` | Marker typo or unregistered marker | Register under `[tool.pytest.ini_options].markers` |
| Tests hang on async code | Forgot `await`, or sync test calling async helper | Make test `async def` and `await` the call |
