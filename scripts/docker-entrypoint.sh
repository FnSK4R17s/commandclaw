#!/bin/bash
# docker-entrypoint.sh — Initialize vault from template if workspace is empty, then run agent.

set -e

WORKSPACE="/workspace"
TEMPLATE="/vault-template"

# If workspace has no IDENTITY.md, initialize from vault template
if [ ! -f "${WORKSPACE}/IDENTITY.md" ] && [ -d "${TEMPLATE}" ]; then
    echo "Initializing vault from template..."
    cp -a "${TEMPLATE}/." "${WORKSPACE}/"

    # Remove template's .git and init fresh
    rm -rf "${WORKSPACE}/.git"
    cd "${WORKSPACE}"
    git init -q
    git config user.email "agent@commandclaw.local"
    git config user.name "${COMMANDCLAW_AGENT_ID:-commandclaw}"
    git add -A
    git commit -q -m "init: ${COMMANDCLAW_AGENT_ID:-agent} from vault template"
    echo "Vault initialized."
fi

# Fix terminal for interactive use (backspace, arrow keys, etc.)
export TERM="${TERM:-xterm-256color}"
stty sane 2>/dev/null || true

# Hand off to the original entrypoint
exec python -m commandclaw "$@"
