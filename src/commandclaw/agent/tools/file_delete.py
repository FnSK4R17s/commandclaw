"""File-delete tool scoped to the vault directory."""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from commandclaw.agent.tools.file_read import _validate_vault_path

logger = logging.getLogger(__name__)


def create_file_delete_tool(vault_path: Path) -> BaseTool:
    """Return a LangChain tool that deletes files inside the vault."""

    @tool
    def file_delete(file_path: str) -> str:
        """Delete a file inside the vault. Cannot delete directories."""
        try:
            resolved = _validate_vault_path(file_path, vault_path)
        except ValueError as exc:
            return f"Error: {exc}"

        if not resolved.exists():
            return f"Error: file not found — {file_path}"

        if not resolved.is_file():
            return f"Error: not a regular file (use bash for directories) — {file_path}"

        try:
            resolved.unlink()
        except PermissionError:
            return f"Error: permission denied — {file_path}"

        logger.info("file_delete: %s", resolved)
        return f"Deleted {file_path}"

    return file_delete
