"""File-read tool scoped to the vault directory."""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.tools import BaseTool, tool

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 500 * 1024  # 500 KB


def _validate_vault_path(file_path: str, vault_path: Path) -> Path:
    """Resolve *file_path* and ensure it lives under *vault_path*.

    Returns the resolved ``Path`` or raises ``ValueError``.
    """
    resolved = (vault_path / file_path).resolve()
    vault_resolved = vault_path.resolve()
    if not str(resolved).startswith(str(vault_resolved) + "/") and resolved != vault_resolved:
        raise ValueError(f"Path {file_path!r} resolves outside the vault")
    return resolved


def create_file_read_tool(vault_path: Path) -> BaseTool:
    """Return a LangChain tool that reads files inside the vault."""

    @tool
    def file_read(file_path: str) -> str:
        """Read a file inside the vault and return its contents."""
        try:
            resolved = _validate_vault_path(file_path, vault_path)
        except ValueError as exc:
            return f"Error: {exc}"

        if not resolved.exists():
            return f"Error: file not found — {file_path}"

        if not resolved.is_file():
            return f"Error: not a regular file — {file_path}"

        try:
            size = resolved.stat().st_size
            if size > MAX_FILE_SIZE:
                return f"Error: file too large ({size} bytes, max {MAX_FILE_SIZE})"

            content = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"Error: file appears to be binary — {file_path}"
        except PermissionError:
            return f"Error: permission denied — {file_path}"

        logger.info("file_read: %s (%d bytes)", resolved, len(content))
        return content

    return file_read
