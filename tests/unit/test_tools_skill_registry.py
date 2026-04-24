"""Tests for skill_registry tools — browse and install from a fake registry.

Tests inject a fake registry dir via monkeypatch instead of cloning from GitHub.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from commandclaw.agent.tools.skill_registry import (
    create_browse_skills_tool,
    create_install_skill_tool,
)


@pytest.fixture
def fake_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a fake skills registry and patch the cache to point at it."""
    import commandclaw.agent.tools.skill_registry as mod

    registry = tmp_path / "registry" / "skills"
    registry.mkdir(parents=True)

    # Skill with valid frontmatter
    skill_a = registry / "alpha"
    skill_a.mkdir()
    (skill_a / "SKILL.md").write_text(
        "---\nname: Alpha Skill\ndescription: Does alpha things\n---\nInstructions here.\n"
    )

    # Skill with valid frontmatter
    skill_b = registry / "beta"
    skill_b.mkdir()
    (skill_b / "SKILL.md").write_text(
        "---\nname: Beta Skill\ndescription: Does beta things\n---\nMore instructions.\n"
    )

    # Directory without SKILL.md (should be skipped)
    (registry / "empty-dir").mkdir()

    monkeypatch.setattr(mod, "_ensure_registry_cache", lambda: registry)
    return registry


# ============================================================
# browse_skills
# ============================================================


class TestBrowseSkills:
    def test_lists_available_skills(self, fake_registry: Path) -> None:
        tool = create_browse_skills_tool()
        result = tool.invoke({})
        assert "Alpha Skill" in result
        assert "Does alpha things" in result
        assert "Beta Skill" in result
        assert "install_skill" in result

    def test_skips_dirs_without_skill_md(self, fake_registry: Path) -> None:
        tool = create_browse_skills_tool()
        result = tool.invoke({})
        assert "empty-dir" not in result

    def test_registry_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import commandclaw.agent.tools.skill_registry as mod

        monkeypatch.setattr(mod, "_ensure_registry_cache", lambda: None)
        tool = create_browse_skills_tool()
        result = tool.invoke({})
        assert "Error" in result

    def test_empty_registry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import commandclaw.agent.tools.skill_registry as mod

        empty = tmp_path / "empty_reg"
        empty.mkdir()
        monkeypatch.setattr(mod, "_ensure_registry_cache", lambda: empty)
        tool = create_browse_skills_tool()
        result = tool.invoke({})
        assert "No skills found" in result


# ============================================================
# install_skill
# ============================================================


class TestInstallSkill:
    def test_installs_skill(self, fake_registry: Path, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        tool = create_install_skill_tool(vault)
        result = tool.invoke({"skill_name": "alpha"})
        assert "Installed" in result
        assert "Alpha Skill" in result
        assert (vault / ".agents" / "skills" / "alpha" / "SKILL.md").exists()

    def test_skill_not_found(self, fake_registry: Path, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        tool = create_install_skill_tool(vault)
        result = tool.invoke({"skill_name": "nonexistent"})
        assert "not found" in result
        assert "alpha" in result  # lists available skills

    def test_already_installed(self, fake_registry: Path, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        dest = vault / ".agents" / "skills" / "alpha"
        dest.mkdir(parents=True)
        tool = create_install_skill_tool(vault)
        result = tool.invoke({"skill_name": "alpha"})
        assert "already installed" in result

    def test_registry_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import commandclaw.agent.tools.skill_registry as mod

        monkeypatch.setattr(mod, "_ensure_registry_cache", lambda: None)
        vault = tmp_path / "vault"
        vault.mkdir()
        tool = create_install_skill_tool(vault)
        result = tool.invoke({"skill_name": "alpha"})
        assert "Error" in result
