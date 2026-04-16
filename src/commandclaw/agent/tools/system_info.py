"""System info tool — lets the agent check its own capabilities and mode."""

from __future__ import annotations

import os
import shutil

from langchain_core.tools import tool


def create_system_info_tool():
    """Create a tool that reports the agent's current runtime capabilities."""

    @tool
    async def system_info() -> str:
        """Check whether you are running in admin or standard mode, along with your current runtime capabilities: available commands, resource limits, and environment. Queries the MCP gateway for policy-driven capabilities when available."""
        admin = os.environ.get("COMMANDCLAW_ADMIN_MODE") == "1"
        agent_id = os.environ.get("COMMANDCLAW_AGENT_ID", "unknown")
        gateway_url = os.environ.get("COMMANDCLAW_MCP_GATEWAY_URL", "")

        lines = [f"Agent ID: {agent_id}"]

        # Query gateway for policy-driven capabilities
        gateway_caps = await _fetch_gateway_capabilities(gateway_url, agent_id)
        if gateway_caps:
            lines += [
                f"Mode: {gateway_caps.get('mode', 'standard').upper()}",
                f"Roles: {', '.join(gateway_caps.get('roles', []))}",
                f"Allowed tool servers: {', '.join(gateway_caps.get('allowed_tools', []))}",
                f"Rate limit: {gateway_caps.get('rate_limit', {}).get('requests_per_minute', 'unlimited')} req/min",
            ]
        else:
            lines.append(f"Mode: {'ADMIN' if admin else 'STANDARD'}")

        lines.append("")

        if admin:
            lines += [
                "Capabilities:",
                "  - Writable filesystem (can install packages)",
                "  - Can run: apt-get install, npm install, npx, pip install",
                "  - Memory: 1GB, CPUs: 2",
            ]
        else:
            lines += [
                "Restrictions:",
                "  - Read-only filesystem (cannot install packages)",
                "  - Blocked: apt-get, npm install, pip install",
                "  - Memory: 512MB, CPUs: 1",
                "",
                "To get admin access, ask your human to restart you with:",
                f"  ./scripts/spawn-agent.sh --admin {agent_id}",
            ]

        # Check available commands
        cmds = ["node", "npm", "npx", "git", "python3", "curl"]
        available = [c for c in cmds if shutil.which(c)]
        missing = [c for c in cmds if not shutil.which(c)]
        lines += [
            "",
            f"Available: {', '.join(available)}",
        ]
        if missing:
            lines += [f"Missing: {', '.join(missing)}"]

        return "\n".join(lines)

    return system_info


async def _fetch_gateway_capabilities(
    gateway_url: str, agent_id: str
) -> dict | None:
    """Query GET /capabilities from the MCP gateway.

    Returns the capabilities dict or None if unreachable.
    """
    if not gateway_url:
        return None

    try:
        import httpx

        base = gateway_url.rstrip("/")
        if base.endswith("/mcp"):
            base = base[:-4]
        url = f"{base}/capabilities"

        async with httpx.AsyncClient(timeout=5.0) as client:
            # Bootstrap a quick session to get a token
            resp = await client.post(
                f"{base}/sessions",
                json={"agent_id": agent_id},
            )
            if resp.status_code != 201:
                return None

            token = resp.json().get("phantom_token")
            if not token:
                return None

            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None
