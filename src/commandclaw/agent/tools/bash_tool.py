"""Shell command execution tool for the CommandClaw agent."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from langchain_core.tools import BaseTool, tool

logger = logging.getLogger(__name__)

MAX_OUTPUT_LENGTH = 50_000


def create_bash_tool(vault_path: Path, timeout: int = 120) -> BaseTool:
    """Return a LangChain tool that executes shell commands inside the vault."""

    @tool
    def bash(command: str) -> str:
        """Execute a shell command and return stdout+stderr."""
        logger.info("bash tool: running %r (timeout=%ds)", command, timeout)
        try:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(vault_path),
            )
        except subprocess.TimeoutExpired:
            msg = f"Command timed out after {timeout}s: {command}"
            logger.warning(msg)
            return msg

        output = result.stdout + result.stderr

        if result.returncode != 0:
            output = f"[exit code {result.returncode}]\n{output}"

        if len(output) > MAX_OUTPUT_LENGTH:
            output = output[:MAX_OUTPUT_LENGTH] + "\n\n[truncated — output exceeded 50 000 chars]"

        return output or "(no output)"

    return bash
