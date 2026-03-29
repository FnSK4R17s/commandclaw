"""Discover and load skills from .agents/skills/*/SKILL.md."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(".agents") / "skills"


@dataclass
class Skill:
    """A single skill parsed from a SKILL.md file."""

    name: str
    description: str
    instructions: str
    path: Path


def _parse_skill(skill_path: Path) -> Skill | None:
    """Parse a SKILL.md file with YAML frontmatter."""
    try:
        post = frontmatter.load(str(skill_path))
        return Skill(
            name=post.get("name", skill_path.parent.name),
            description=post.get("description", ""),
            instructions=post.content,
            path=skill_path,
        )
    except Exception:
        logger.warning("Failed to parse skill: %s", skill_path, exc_info=True)
        return None


def discover_skills(vault_path: Path) -> list[Skill]:
    """Scan .agents/skills/*/SKILL.md and return all valid skills."""
    skills_dir = vault_path / _SKILLS_DIR
    if not skills_dir.exists():
        return []

    skills: list[Skill] = []
    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        skill = _parse_skill(skill_file)
        if skill is not None:
            skills.append(skill)

    logger.info("Discovered %d skill(s)", len(skills))
    return skills


def load_skill(vault_path: Path, name: str) -> Skill | None:
    """Load a single skill by directory name."""
    skill_path = vault_path / _SKILLS_DIR / name / "SKILL.md"
    if not skill_path.exists():
        logger.debug("Skill not found: %s", name)
        return None
    return _parse_skill(skill_path)
