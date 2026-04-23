"""Skill registry tools — browse and install skills from the official repo."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from langchain_core.tools import BaseTool, tool

logger = logging.getLogger(__name__)

SKILLS_REPO = "https://github.com/FnSK4R17s/commandclaw-skills.git"
SKILLS_CACHE = Path("/tmp/commandclaw-skills-registry")


def _ensure_registry_cache() -> Path | None:
    """Clone or update the skills registry cache. Returns the skills dir or None."""
    try:
        if (SKILLS_CACHE / "skills").exists():
            # Pull latest
            subprocess.run(
                ["git", "-C", str(SKILLS_CACHE), "pull", "--quiet"],
                capture_output=True, timeout=30,
            )
        else:
            SKILLS_CACHE.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", "--depth=1", "--quiet", SKILLS_REPO, str(SKILLS_CACHE)],
                capture_output=True, timeout=60, check=True,
            )
        return SKILLS_CACHE / "skills"
    except Exception:
        logger.exception("Failed to fetch skills registry")
        return None


def create_browse_skills_tool() -> BaseTool:
    """Tool to list all available skills from the official registry."""

    @tool
    def browse_skills() -> str:
        """Browse the official CommandClaw skills registry. Shows all available skills with descriptions that can be installed."""
        registry = _ensure_registry_cache()
        if registry is None or not registry.exists():
            return "Error: could not fetch the skills registry from GitHub."

        lines = ["Available skills from the official registry:\n"]
        for skill_dir in sorted(registry.iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                import frontmatter
                post = frontmatter.load(str(skill_md))
                name = post.get("name", skill_dir.name)
                desc = post.get("description", "(no description)")
                lines.append(f"- **{name}**: {desc}")
            except Exception:
                lines.append(f"- **{skill_dir.name}**: (could not parse)")

        if len(lines) == 1:
            return "No skills found in the registry."

        lines.append("\nTo install a skill, use: install_skill(\"<skill-name>\")")

        import os
        if os.environ.get("COMMANDCLAW_ADMIN_MODE") == "1":
            lines.append(
                "\nNote (admin mode): You can also install skills interactively with dependency scanning using "
                "Vercel's skills CLI:\n"
                "  npx skills add FnSK4R17s/commandclaw-skills   (official CommandClaw skills)\n"
                "  npx skills add <owner/repo>                    (any compatible skills repo)"
            )

        return "\n".join(lines)

    return browse_skills


def create_install_skill_tool(vault_path: Path) -> BaseTool:
    """Tool to install a skill from the official registry into the vault."""

    @tool
    def install_skill(skill_name: str) -> str:
        """Install a skill from the official CommandClaw skills registry into your workspace. Use browse_skills() first to see what's available."""
        registry = _ensure_registry_cache()
        if registry is None or not registry.exists():
            return "Error: could not fetch the skills registry."

        source = registry / skill_name
        if not source.exists() or not (source / "SKILL.md").exists():
            available = [d.name for d in registry.iterdir() if (d / "SKILL.md").exists()]
            return (
                f"Skill '{skill_name}' not found in the registry.\n"
                f"Available: {', '.join(available)}"
            )

        dest = vault_path / ".agents" / "skills" / skill_name
        if dest.exists():
            return f"Skill '{skill_name}' is already installed at {dest}"

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, dest)

            # Parse and return confirmation
            import frontmatter
            post = frontmatter.load(str(dest / "SKILL.md"))
            name = post.get("name", skill_name)
            desc = post.get("description", "")
            return f"Installed skill '{name}': {desc}\nLocation: {dest}"
        except Exception as exc:
            logger.exception("Failed to install skill '%s'", skill_name)
            return f"Error installing skill '{skill_name}': {exc}"

    return install_skill
