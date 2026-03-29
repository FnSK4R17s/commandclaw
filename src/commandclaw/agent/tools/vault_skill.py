"""Vault skill discovery and reading tools."""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from commandclaw.vault.skills import discover_skills, load_skill

logger = logging.getLogger(__name__)


def create_list_skills_tool(vault_path: Path) -> BaseTool:
    """Return a tool that lists all discovered skills with descriptions."""

    @tool
    def list_skills() -> str:
        """List all available skills (name + description)."""
        try:
            skills = discover_skills(vault_path)
            if not skills:
                return "(no skills found in vault)"

            lines = [f"- **{s.name}**: {s.description}" for s in skills]
            return "\n".join(lines)
        except Exception as exc:
            logger.exception("list_skills failed")
            return f"Error discovering skills: {exc}"

    return list_skills


def create_read_skill_tool(vault_path: Path) -> BaseTool:
    """Return a tool that loads full instructions for a named skill."""

    @tool
    def read_skill(skill_name: str) -> str:
        """Load the full instructions for a skill by name."""
        try:
            skill = load_skill(vault_path, skill_name)
            if skill is None:
                return f"Error: skill {skill_name!r} not found"

            parts = [
                f"# {skill.name}",
                f"\n{skill.description}",
                f"\n## Instructions\n\n{skill.instructions}",
            ]
            return "\n".join(parts)
        except Exception as exc:
            logger.exception("read_skill failed")
            return f"Error loading skill {skill_name!r}: {exc}"

    return read_skill
