.PHONY: build agent agent-admin agent-new agent-list agent-rm chat

# Build the agent Docker image
build:
	docker build -t commandclaw:latest .

# Spawn a new agent (auto-generated ID, bootstraps on first run)
agent:
	@./scripts/spawn-agent.sh

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
