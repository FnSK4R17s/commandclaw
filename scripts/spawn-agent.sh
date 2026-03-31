#!/usr/bin/env bash
# spawn-agent.sh — Create a workspace and launch an agent in a persistent container.
#
# Usage:
#   ./scripts/spawn-agent.sh                    # New agent (auto-generated ID)
#   ./scripts/spawn-agent.sh brave-panda-4821   # Resume existing agent
#   ./scripts/spawn-agent.sh --admin            # New agent in admin mode
#   ./scripts/spawn-agent.sh --admin brave-panda  # Resume in admin mode
#   ./scripts/spawn-agent.sh --list             # List all agents
#   ./scripts/spawn-agent.sh --rm brave-panda   # Remove an agent
#
# Admin mode:
#   - Writable filesystem (can install packages, skills)
#   - 1GB memory (vs 512MB default)
#   - No read-only restriction
#   - Same network access and tracing
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
MCP_NETWORK="${COMMANDCLAW_MCP_NETWORK:-commandclaw-mcp_default}"
OBSERVE_NETWORK="${COMMANDCLAW_OBSERVE_NETWORK:-commandclaw-observe_default}"

# --- Word lists (matching workspace.py and chakravarti-cli) ---
ADJECTIVES=(bold brave calm cool crisp deft fair fast fine firm fond free glad gold good keen kind lean live neat nice pure rare rich safe sage slim soft sure tall tidy true vast warm wide wild wise zany epic swift)
ANIMALS=(ape bat bear bison boar bull civet cobra crane crow deer dove eagle fox frog gaur gecko goat hawk hare heron ibis jackal kite koel langur lion moth mongoose myna newt otter owl panda peacock rat rhino robin shrew stork tiger viper wolf)

ADMIN_MODE=false

generate_agent_id() {
    local hash adj_idx animal_idx suffix
    hash=$(date +%s%N | sha256sum | cut -c1-12)
    # Use small slices to avoid bash integer overflow
    adj_idx=$(( 16#${hash:0:4} % ${#ADJECTIVES[@]} ))
    animal_idx=$(( 16#${hash:4:4} % ${#ANIMALS[@]} ))
    suffix=$(( 16#${hash:8:4} % 10000 ))
    printf '%s-%s-%04d' "${ADJECTIVES[$adj_idx]}" "${ANIMALS[$animal_idx]}" "$suffix"
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
        printf "  %-30s %s\n" "$name" "($container_status)"
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

    if [ "$ADMIN_MODE" = true ]; then
        echo "  Mode: ADMIN (writable fs, 1GB memory)"
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
        ADMIN_MODE=true
        if [ -n "${2:-}" ]; then
            # Explicit agent ID in admin mode
            AGENT_ID="$2"
        else
            # Generate new agent in admin mode
            AGENT_ID=$(generate_agent_id)
        fi
        ensure_workspace_dir "$AGENT_ID"
        spawn_container "$AGENT_ID"
        ;;
    --help|-h)
        echo "Usage:"
        echo "  $0                        Spawn new agent (auto-generated ID)"
        echo "  $0 <agent-id>             Resume or create agent with specific ID"
        echo "  $0 --admin [agent-id]     Spawn/resume in admin mode (writable fs, can install packages)"
        echo "  $0 --list                 List all agents and their status"
        echo "  $0 --rm <agent-id>        Remove an agent (container + workspace)"
        echo ""
        echo "Environment:"
        echo "  COMMANDCLAW_IMAGE          Docker image (default: commandclaw:latest)"
        echo "  COMMANDCLAW_VAULT_TEMPLATE Vault template path (default: /apps/commandclaw-vault)"
        echo "  COMMANDCLAW_ENV_FILE       Path to .env file (default: /apps/commandclaw/.env)"
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
