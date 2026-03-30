#!/usr/bin/env bash
# spawn-agent.sh — Create a workspace and launch an agent in a persistent container.
#
# Usage:
#   ./scripts/spawn-agent.sh                    # New agent (auto-generated ID)
#   ./scripts/spawn-agent.sh brave-panda-4821   # Resume existing agent
#   ./scripts/spawn-agent.sh --list             # List all agents
#   ./scripts/spawn-agent.sh --rm brave-panda   # Remove an agent
#
# The agent runs inside a Docker container with:
#   - /workspace mounted from ~/.commandclaw/workspaces/<agent-id>/
#   - No host filesystem access beyond the vault
#   - MCP gateway accessible via Docker network
#   - Persistent across restarts (docker start/stop)

set -euo pipefail

IMAGE="${COMMANDCLAW_IMAGE:-commandclaw:local}"
VAULT_TEMPLATE="${COMMANDCLAW_VAULT_TEMPLATE:-/apps/commandclaw-vault}"
WORKSPACES_DIR="${HOME}/.commandclaw/workspaces"
ENV_FILE="${COMMANDCLAW_ENV_FILE:-/apps/commandclaw/.env}"
MCP_NETWORK="${COMMANDCLAW_MCP_NETWORK:-commandclaw-mcp_default}"

# --- Word lists (matching workspace.py and chakravarti-cli) ---
ADJECTIVES=(bold brave calm cool crisp deft fair fast fine firm fond free glad gold good keen kind lean live neat nice pure rare rich safe sage slim soft sure tall tidy true vast warm wide wild wise zany epic swift)
ANIMALS=(ape bat bear bison boar bull civet cobra crane crow deer dove eagle fox frog gaur gecko goat hawk hare heron ibis jackal kite koel langur lion moth mongoose myna newt otter owl panda peacock rat rhino robin shrew stork tiger viper wolf)

generate_agent_id() {
    local ns adj animal suffix
    ns=$(date +%s%N)
    hash=$(echo -n "$ns" | sha256sum | cut -c1-16)
    hash_int=$((16#$hash))
    adj=${ADJECTIVES[$((hash_int % ${#ADJECTIVES[@]}))]}
    animal=${ANIMALS[$(((hash_int >> 16) % ${#ANIMALS[@]}))]}
    suffix=$(( (hash_int >> 32) % 10000 ))
    printf '%s-%s-%04d' "$adj" "$animal" "$suffix"
}

create_workspace() {
    local agent_id="$1"
    local ws_path="${WORKSPACES_DIR}/${agent_id}"

    if [ -d "$ws_path" ]; then
        echo "Reusing workspace: ${agent_id}"
        return 0
    fi

    if [ ! -d "$VAULT_TEMPLATE" ]; then
        echo "Error: Vault template not found at ${VAULT_TEMPLATE}" >&2
        echo "Clone it: git clone https://github.com/FnSK4R17s/commandclaw-vault ${VAULT_TEMPLATE}" >&2
        exit 1
    fi

    mkdir -p "$WORKSPACES_DIR"

    # Copy template (exclude .git)
    rsync -a --exclude='.git' "${VAULT_TEMPLATE}/" "${ws_path}/"

    # Init fresh git repo
    git -C "$ws_path" init -q
    git -C "$ws_path" add -A
    git -C "$ws_path" commit -q -m "init: ${agent_id} from commandclaw-vault template"

    echo "Created workspace: ${agent_id}"
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
        local name=$(basename "$ws")
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

    echo "Spawning agent: ${agent_id}"
    echo "  Workspace: ${ws_path}"
    echo "  Container: ${container_name}"
    echo ""

    docker run -it \
        --name "${container_name}" \
        --hostname "${agent_id}" \
        --volume "${ws_path}:/workspace" \
        --env-file "${ENV_FILE}" \
        --env "COMMANDCLAW_VAULT_PATH=/workspace" \
        --env "COMMANDCLAW_AGENT_ID=${agent_id}" \
        --network "${MCP_NETWORK}" \
        --restart unless-stopped \
        --memory 512m \
        --cpus 1 \
        --read-only \
        --tmpfs /tmp:size=100m \
        --tmpfs /home/agent:size=50m \
        "${IMAGE}" "${mode}"
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
    --help|-h)
        echo "Usage:"
        echo "  $0                        Spawn new agent (auto-generated ID)"
        echo "  $0 <agent-id>             Resume or create agent with specific ID"
        echo "  $0 --list                 List all agents and their status"
        echo "  $0 --rm <agent-id>        Remove an agent (container + workspace)"
        echo ""
        echo "Environment:"
        echo "  COMMANDCLAW_IMAGE          Docker image (default: commandclaw:local)"
        echo "  COMMANDCLAW_VAULT_TEMPLATE Vault template path (default: /apps/commandclaw-vault)"
        echo "  COMMANDCLAW_ENV_FILE       Path to .env file (default: /apps/commandclaw/.env)"
        echo "  COMMANDCLAW_MCP_NETWORK    Docker network for MCP gateway (default: commandclaw-mcp_default)"
        ;;
    "")
        # No args — generate new agent
        AGENT_ID=$(generate_agent_id)
        create_workspace "$AGENT_ID"
        spawn_container "$AGENT_ID"
        ;;
    *)
        # Explicit agent ID
        AGENT_ID="$1"
        create_workspace "$AGENT_ID"
        spawn_container "$AGENT_ID"
        ;;
esac
