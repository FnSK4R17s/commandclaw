"""Tests for vault_memory and vault_skill tool wrappers."""

from __future__ import annotations

from pathlib import Path

from commandclaw.agent.tools.vault_memory import create_memory_read_tool, create_memory_write_tool
from commandclaw.agent.tools.vault_skill import create_list_skills_tool, create_read_skill_tool
from commandclaw.vault.git_ops import VaultRepo

# ============================================================
# Helper — set up a vault with skills
# ============================================================


def _install_skill(vault: Path, name: str, desc: str = "A skill", body: str = "Do things.") -> None:
    skill_dir = vault / ".agents" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n{body}\n"
    )


# ============================================================
# memory_read
# ============================================================


class TestMemoryRead:
    def test_empty_vault_returns_no_entries(self, tmp_vault: Path) -> None:
        tool = create_memory_read_tool(tmp_vault)
        result = tool.invoke({})
        assert "no memory entries" in result

    def test_reads_long_term_memory(self, tmp_vault: Path) -> None:
        (tmp_vault / "MEMORY.md").write_text("# Long-term\n\nRemember this.")
        tool = create_memory_read_tool(tmp_vault)
        result = tool.invoke({})
        assert "Remember this" in result
        assert "Long-term memory" in result


# ============================================================
# memory_write
# ============================================================


class TestMemoryWrite:
    def test_writes_daily_note(self, tmp_vault: Path, tmp_vault_repo: VaultRepo) -> None:
        tmp_vault_repo.repo.index.add([str(p) for p in tmp_vault.glob("*.md")])
        tmp_vault_repo.repo.index.commit("init: seed vault")
        tool = create_memory_write_tool(tmp_vault, tmp_vault_repo)
        result = tool.invoke({"entry": "Today I learned something."})
        assert "Saved" in result

        memory_dir = tmp_vault / "memory"
        assert memory_dir.exists()
        notes = list(memory_dir.glob("*.md"))
        assert len(notes) >= 1
        content = notes[0].read_text()
        assert "Today I learned something" in content


# ============================================================
# list_skills
# ============================================================


class TestListSkills:
    def test_no_skills(self, tmp_vault: Path) -> None:
        tool = create_list_skills_tool(tmp_vault)
        result = tool.invoke({})
        assert "no skills found" in result

    def test_lists_installed_skills(self, tmp_vault: Path) -> None:
        _install_skill(tmp_vault, "greeting", desc="Say hello")
        _install_skill(tmp_vault, "farewell", desc="Say goodbye")
        tool = create_list_skills_tool(tmp_vault)
        result = tool.invoke({})
        assert "greeting" in result
        assert "Say hello" in result
        assert "farewell" in result
        assert "Say goodbye" in result


# ============================================================
# read_skill
# ============================================================


class TestReadSkill:
    def test_reads_skill(self, tmp_vault: Path) -> None:
        _install_skill(tmp_vault, "helper", desc="Helps", body="Step 1: help.")
        tool = create_read_skill_tool(tmp_vault)
        result = tool.invoke({"skill_name": "helper"})
        assert "helper" in result
        assert "Step 1: help" in result

    def test_skill_not_found(self, tmp_vault: Path) -> None:
        tool = create_read_skill_tool(tmp_vault)
        result = tool.invoke({"skill_name": "nonexistent"})
        assert "Error" in result
        assert "not found" in result
