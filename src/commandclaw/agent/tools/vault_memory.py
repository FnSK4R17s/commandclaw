"""Vault memory tools — read/write long-term memory and daily notes."""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from commandclaw.vault.git_ops import VaultRepo
from commandclaw.vault.memory import (
    read_daily_notes,
    read_long_term_memory,
    write_daily_note,
)

logger = logging.getLogger(__name__)


def create_memory_read_tool(vault_path: Path) -> BaseTool:
    """Return a tool that reads long-term memory and recent daily notes."""

    @tool
    def memory_read() -> str:
        """Read long-term memory and the last 2 days of daily notes."""
        try:
            long_term = read_long_term_memory(vault_path)
            daily = read_daily_notes(vault_path, days=2)

            parts: list[str] = []
            if long_term:
                parts.append("## Long-term memory\n\n" + long_term)
            if daily:
                notes = "\n\n".join(
                    f"### {day}\n{content}" for day, content in sorted(daily.items(), reverse=True)
                )
                parts.append("## Recent daily notes\n\n" + notes)

            if not parts:
                return "(no memory entries found)"

            return "\n\n---\n\n".join(parts)
        except Exception as exc:
            logger.exception("memory_read failed")
            return f"Error reading memory: {exc}"

    return memory_read


def create_memory_write_tool(vault_path: Path, repo: VaultRepo) -> BaseTool:
    """Return a tool that appends an entry to today's daily note."""

    @tool
    def memory_write(entry: str) -> str:
        """Write an entry to today's daily note and auto-commit."""
        try:
            write_daily_note(vault_path, entry, repo)
            logger.info("memory_write: committed daily note entry")
            return "Saved to today's daily note."
        except Exception as exc:
            logger.exception("memory_write failed")
            return f"Error writing memory: {exc}"

    return memory_write
