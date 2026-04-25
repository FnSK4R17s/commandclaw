.PHONY: build agent agent-admin agent-new agent-list agent-rm chat \
       test test-unit test-integration test-agent test-e2e test-all test-cov \
       lint lint-fix install

# ============================================================
# Setup
# ============================================================

install:
	python3 -m venv .venv
	./.venv/bin/pip install -e '.[dev]'

# ============================================================
# Docker / agents
# ============================================================

build:
	docker build -t commandclaw:latest .

agent:
	@./scripts/spawn-agent.sh $(ID)

agent-admin:
	@./scripts/spawn-agent.sh --admin $(ID)

agent-new:
	@./scripts/spawn-agent.sh $(ID)

agent-list:
	@./scripts/spawn-agent.sh --list

# Usage: make agent-rm ID=brave-panda-4821
agent-rm:
	@./scripts/spawn-agent.sh --rm $(ID)

chat:
	docker compose run --rm agent chat

# ============================================================
# Lint
# ============================================================

lint:
	./.venv/bin/ruff check .

lint-fix:
	./.venv/bin/ruff check --fix .

# ============================================================
# Tests
# ============================================================

# Fast tier — unit + agent-with-fake-LLM. Default for TDD loops.
test:
	./.venv/bin/pytest tests/unit tests/agent

test-unit:
	./.venv/bin/pytest tests/unit

test-integration:
	./.venv/bin/pytest tests/integration

test-agent:
	./.venv/bin/pytest tests/agent

# E2e — source .env.test for host-side keys (localhost URLs, enrolled agent).
# Usage: make test-e2e
test-e2e:
	@test -f .env.test || { echo "Missing .env.test — see .env.test header for setup"; exit 1; }
	@set -a && . ./.env.test && set +a && ./.venv/bin/pytest tests/e2e -m e2e -v

# Everything except e2e.
test-all:
	./.venv/bin/pytest tests/unit tests/integration tests/agent

# Coverage report (excludes e2e).
test-cov:
	./.venv/bin/pytest tests/unit tests/integration tests/agent --cov=commandclaw --cov-report=term-missing
