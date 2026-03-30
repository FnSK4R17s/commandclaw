"""File-list tool scoped to the vault directory."""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from commandclaw.agent.tools.file_read import _validate_vault_path

logger = logging.getLogger(__name__)


def create_file_list_tool(vault_path: Path) -> BaseTool:
    """Return a LangChain tool that lists files and directories inside the vault."""

    @tool
    def file_list(directory: str = ".") -> str:
        """List files and directories inside a vault directory. Defaults to vault root."""
        try:
            resolved = _validate_vault_path(directory, vault_path)
        except ValueError as exc:
            return f"Error: {exc}"

        if not resolved.exists():
            return f"Error: directory not found — {directory}"

        if not resolved.is_dir():
            return f"Error: not a directory — {directory}"

        entries = []
        for entry in sorted(resolved.iterdir()):
            rel = entry.relative_to(vault_path)
            suffix = "/" if entry.is_dir() else ""
            entries.append(f"{rel}{suffix}")

        logger.info("file_list: %s (%d entries)", resolved, len(entries))
        return "\n".join(entries) if entries else "(empty directory)"

    return file_list
