"""File-write tool scoped to the vault directory."""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from commandclaw.agent.tools.file_read import _validate_vault_path

logger = logging.getLogger(__name__)


def create_file_write_tool(vault_path: Path) -> BaseTool:
    """Return a LangChain tool that writes files inside the vault."""

    @tool
    def file_write(file_path: str, content: str) -> str:
        """Write content to a file inside the vault (creates or overwrites)."""
        try:
            resolved = _validate_vault_path(file_path, vault_path)
        except ValueError as exc:
            return f"Error: {exc}"

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
        except PermissionError:
            return f"Error: permission denied — {file_path}"
        except OSError as exc:
            return f"Error writing file: {exc}"

        logger.info("file_write: %s (%d bytes)", resolved, len(content))
        return f"Wrote {len(content)} bytes to {file_path}"

    return file_write
