.PHONY: build agent agent-admin agent-new agent-list agent-rm chat test test-unit test-integration test-agent test-e2e test-all test-cov

# Build the agent Docker image
build:
	docker build -t commandclaw:latest .

# Spawn a new agent (auto-generated ID, or resume with ID=<agent-id>)
agent:
	@./scripts/spawn-agent.sh $(ID)

# Spawn a new agent in admin mode (writable fs, can install packages/skills)
agent-admin:
	@./scripts/spawn-agent.sh --admin $(ID)

# Spawn with a specific agent ID
# Usage: make agent-new ID=my-agent-name
agent-new:
	@./scripts/spawn-agent.sh $(ID)

# List all agents and their status
agent-list:
	@./scripts/spawn-agent.sh --list

# Remove an agent
# Usage: make agent-rm ID=brave-panda-4821
agent-rm:
	@./scripts/spawn-agent.sh --rm $(ID)

# Quick chat using docker-compose (uses ./vault/ directory)
chat:
	docker compose run --rm agent chat

# Fast tier — pure unit + agent-with-fake-LLM. Default for TDD loops.
test:
	./.venv/bin/pytest tests/unit tests/agent

test-unit:
	./.venv/bin/pytest tests/unit

test-integration:
	./.venv/bin/pytest tests/integration

test-agent:
	./.venv/bin/pytest tests/agent

# Opt-in — needs OPENAI_API_KEY + LANGFUSE_* in the env.
test-e2e:
	./.venv/bin/pytest tests/e2e -m e2e

# Everything except e2e.
test-all:
	./.venv/bin/pytest tests/unit tests/integration tests/agent

test-cov:
	./.venv/bin/pytest tests/unit tests/integration tests/agent --cov=commandclaw --cov-report=term-missing
