#!/usr/bin/env bash
# spawn-agent.sh — Create a workspace and launch an agent in a persistent container.
#
# Usage:
#   ./scripts/spawn-agent.sh                    # New agent (auto-generated ID)
#   ./scripts/spawn-agent.sh brave-panda-4821   # Resume existing agent
#   ./scripts/spawn-agent.sh --list             # List all agents
#   ./scripts/spawn-agent.sh --rm brave-panda   # Remove an agent
#
# Agent mode (admin vs standard) is read from ~/.commandclaw/agents.json.
# No --admin flag — the gateway's agents.json is the single source of truth.
#
# The agent runs inside a Docker container with:
#   - /workspace mounted from ~/.commandclaw/workspaces/<agent-id>/
#   - Vault template cloned inside the container (correct permissions)
#   - MCP gateway + Langfuse accessible via Docker networks
#   - Persistent across restarts (docker start/stop)

set -euo pipefail

IMAGE="${COMMANDCLAW_IMAGE:-commandclaw:latest}"
VAULT_TEMPLATE="${COMMANDCLAW_VAULT_TEMPLATE:-/apps/commandclaw-vault}"
WORKSPACES_DIR="${HOME}/.commandclaw/workspaces"
ENV_FILE="${COMMANDCLAW_ENV_FILE:-/apps/commandclaw/.env}"
AGENTS_JSON="${COMMANDCLAW_AGENTS_JSON:-${HOME}/.commandclaw/agents.json}"
MCP_NETWORK="${COMMANDCLAW_MCP_NETWORK:-commandclaw-mcp_default}"
OBSERVE_NETWORK="${COMMANDCLAW_OBSERVE_NETWORK:-commandclaw-observe_default}"

# --- Word lists (matching workspace.py and chakravarti-cli) ---
ADJECTIVES=(bold brave calm cool crisp deft fair fast fine firm fond free glad gold good keen kind lean live neat nice pure rare rich safe sage slim soft sure tall tidy true vast warm wide wild wise zany epic swift)
ANIMALS=(ape bat bear bison boar bull civet cobra crane crow deer dove eagle fox frog gaur gecko goat hawk hare heron ibis jackal kite koel langur lion moth mongoose myna newt otter owl panda peacock rat rhino robin shrew stork tiger viper wolf)

generate_agent_id() {
    local hash adj_idx animal_idx suffix
    hash=$(date +%s%N | sha256sum | cut -c1-12)
    # Use small slices to avoid bash integer overflow
    adj_idx=$(( 16#${hash:0:4} % ${#ADJECTIVES[@]} ))
    animal_idx=$(( 16#${hash:4:4} % ${#ANIMALS[@]} ))
    suffix=$(( 16#${hash:8:4} % 10000 ))
    printf '%s-%s-%04d' "${ADJECTIVES[$adj_idx]}" "${ANIMALS[$animal_idx]}" "$suffix"
}

get_agent_mode() {
    # Read mode from agents.json. Falls back: agent entry → "default" entry → "standard".
    local agent_id="$1"

    if [ ! -f "$AGENTS_JSON" ]; then
        echo "standard"
        return
    fi

    # Try the specific agent first, then the "default" entry
    local mode
    mode=$(python3 -c "
import json, sys
with open('${AGENTS_JSON}') as f:
    data = json.load(f)
entry = data.get('${agent_id}') or data.get('default') or {}
print(entry.get('mode', 'standard'))
" 2>/dev/null || echo "standard")

    echo "$mode"
}

ensure_workspace_dir() {
    local agent_id="$1"
    local ws_path="${WORKSPACES_DIR}/${agent_id}"

    if [ -d "$ws_path" ]; then
        echo "Reusing workspace: ${agent_id}"
    else
        mkdir -p "$ws_path"
        echo "Created workspace dir: ${agent_id}"
    fi
}

list_agents() {
    echo "Agents:"
    echo ""
    if [ ! -d "$WORKSPACES_DIR" ]; then
        echo "  (none)"
        return
    fi
    for ws in "$WORKSPACES_DIR"/*/; do
        [ -d "$ws" ] || continue
        local name
        name=$(basename "$ws")
        local container_status="not running"
        if docker ps -q --filter "name=cclaw-${name}" 2>/dev/null | grep -q .; then
            container_status="running"
        elif docker ps -aq --filter "name=cclaw-${name}" 2>/dev/null | grep -q .; then
            container_status="stopped"
        fi
        local mode
        mode=$(get_agent_mode "$name")
        printf "  %-30s %-10s %s\n" "$name" "($mode)" "($container_status)"
    done
}

remove_agent() {
    local agent_id="$1"
    local ws_path="${WORKSPACES_DIR}/${agent_id}"
    local container_name="cclaw-${agent_id}"

    # Stop and remove container if exists
    if docker ps -aq --filter "name=${container_name}" 2>/dev/null | grep -q .; then
        echo "Stopping container: ${container_name}"
        docker rm -f "${container_name}" >/dev/null 2>&1 || true
    fi

    # Remove workspace
    if [ -d "$ws_path" ]; then
        rm -rf "$ws_path"
        echo "Removed workspace: ${agent_id}"
    else
        echo "Workspace not found: ${agent_id}" >&2
        exit 1
    fi
}

spawn_container() {
    local agent_id="$1"
    local mode="${2:-chat}"
    local container_name="cclaw-${agent_id}"
    local ws_path="${WORKSPACES_DIR}/${agent_id}"

    # Check if already running
    if docker ps -q --filter "name=${container_name}" 2>/dev/null | grep -q .; then
        echo "Agent ${agent_id} is already running. Attaching..."
        docker attach "${container_name}"
        return
    fi

    # Check if stopped container exists — restart it
    if docker ps -aq --filter "name=${container_name}" 2>/dev/null | grep -q .; then
        echo "Restarting stopped agent: ${agent_id}"
        docker start -ai "${container_name}"
        return
    fi

    # Build image if needed
    if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
        echo "Building agent image..."
        docker build -t "$IMAGE" /apps/commandclaw
    fi

    # Check vault template exists
    if [ ! -d "$VAULT_TEMPLATE" ]; then
        echo "Error: Vault template not found at ${VAULT_TEMPLATE}" >&2
        echo "Clone it: git clone https://github.com/FnSK4R17s/commandclaw-vault ${VAULT_TEMPLATE}" >&2
        exit 1
    fi

    # Read agent mode from agents.json (single source of truth)
    local agent_mode
    agent_mode=$(get_agent_mode "$agent_id")

    # Extract OPENAI_API_KEY from env file for NeMo guardrails
    local openai_key
    openai_key=$(grep -E '^COMMANDCLAW_OPENAI_API_KEY=' "$ENV_FILE" | cut -d= -f2-)

    # Restart policy: only auto-restart for telegram (daemon) mode
    local restart_policy="no"
    if [ "$mode" = "telegram" ]; then
        restart_policy="unless-stopped"
    fi

    # Build docker create args
    local -a create_args=(
        -it
        --name "${container_name}"
        --hostname "${agent_id}"
        --volume "${ws_path}:/workspace"
        --volume "${VAULT_TEMPLATE}:/vault-template:ro"
        --env-file "${ENV_FILE}"
        --env "COMMANDCLAW_VAULT_PATH=/workspace"
        --env "COMMANDCLAW_AGENT_ID=${agent_id}"
        --env "COMMANDCLAW_LANGFUSE_HOST=http://langfuse-web:3000"
        --env "OPENAI_API_KEY=${openai_key}"
        --network "${MCP_NETWORK}"
        --restart "${restart_policy}"
    )

    if [ "$agent_mode" = "admin" ]; then
        echo "  Mode: ADMIN (writable fs, 1GB memory) — from agents.json"
        create_args+=(
            --memory 1g
            --cpus 2
            --env "COMMANDCLAW_ADMIN_MODE=1"
        )
    else
        echo "  Mode: standard (read-only fs, 512MB memory)"
        create_args+=(
            --memory 512m
            --cpus 1
            --read-only
            --tmpfs /tmp:size=100m
            --tmpfs /home/agent:size=50m
        )
    fi

    echo "Spawning agent: ${agent_id}"
    echo "  Workspace: ${ws_path}"
    echo "  Container: ${container_name}"
    echo ""

    # Create container
    docker create "${create_args[@]}" "${IMAGE}" "${mode}" >/dev/null

    # Connect to observe network (Langfuse) — ignore if network doesn't exist
    docker network connect "${OBSERVE_NETWORK}" "${container_name}" 2>/dev/null || true

    # Start and attach
    docker start -ai "${container_name}"
}

# --- Main ---

case "${1:-}" in
    --list|-l)
        list_agents
        ;;
    --rm|--remove)
        if [ -z "${2:-}" ]; then
            echo "Usage: $0 --rm <agent-id>" >&2
            exit 1
        fi
        remove_agent "$2"
        ;;
    --admin|-a)
        echo "The --admin flag has been removed." >&2
        echo "Agent mode is now read from agents.json (single source of truth)." >&2
        echo "" >&2
        echo "To make an agent admin, edit: ${AGENTS_JSON}" >&2
        echo '  e.g. "my-agent": {"roles": ["developer"], "tools": ["clock"], "mode": "admin"}' >&2
        exit 1
        ;;
    --help|-h)
        echo "Usage:"
        echo "  $0                        Spawn new agent (auto-generated ID)"
        echo "  $0 <agent-id>             Resume or create agent with specific ID"
        echo "  $0 --list                 List all agents and their status"
        echo "  $0 --rm <agent-id>        Remove an agent (container + workspace)"
        echo ""
        echo "Agent mode (admin/standard) is read from agents.json — no flag needed."
        echo "Edit ${AGENTS_JSON} to change an agent's mode."
        echo ""
        echo "Environment:"
        echo "  COMMANDCLAW_IMAGE          Docker image (default: commandclaw:latest)"
        echo "  COMMANDCLAW_VAULT_TEMPLATE Vault template path (default: /apps/commandclaw-vault)"
        echo "  COMMANDCLAW_ENV_FILE       Path to .env file (default: /apps/commandclaw/.env)"
        echo "  COMMANDCLAW_AGENTS_JSON    Path to agents.json (default: ~/.commandclaw/agents.json)"
        echo "  COMMANDCLAW_MCP_NETWORK    Docker network for MCP gateway (default: commandclaw-mcp_default)"
        ;;
    "")
        # No args — generate new agent
        AGENT_ID=$(generate_agent_id)
        ensure_workspace_dir "$AGENT_ID"
        spawn_container "$AGENT_ID"
        ;;
    *)
        # Explicit agent ID
        AGENT_ID="$1"
        ensure_workspace_dir "$AGENT_ID"
        spawn_container "$AGENT_ID"
        ;;
esac
