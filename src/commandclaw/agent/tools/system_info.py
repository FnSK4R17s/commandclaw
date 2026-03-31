"""System info tool — lets the agent check its own capabilities and mode."""

from __future__ import annotations

import os
import shutil

from langchain_core.tools import tool


def create_system_info_tool():
    """Create a tool that reports the agent's current runtime capabilities."""

    @tool
    def system_info() -> str:
        """Check whether you are running in admin or standard mode, along with your current runtime capabilities: available commands, resource limits, and environment."""
        admin = os.environ.get("COMMANDCLAW_ADMIN_MODE") == "1"
        agent_id = os.environ.get("COMMANDCLAW_AGENT_ID", "unknown")

        lines = [
            f"Agent ID: {agent_id}",
            f"Mode: {'ADMIN' if admin else 'STANDARD'}",
            "",
            "Capabilities:" if admin else "Restrictions:",
        ]

        if admin:
            lines += [
                "  - Writable filesystem (can install packages)",
                "  - Can run: apt-get install, npm install, npx, pip install",
                "  - Memory: 1GB, CPUs: 2",
            ]
        else:
            lines += [
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
