"""Tests for commandclaw.vault.skills and commandclaw.vault.recovery."""

from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

from commandclaw.vault.git_ops import VaultRepo
from commandclaw.vault.recovery import check_vault_health, recover_vault
from commandclaw.vault.skills import Skill, discover_skills, load_skill


def _make_skill(vault_path: Path, name: str, desc: str, body: str) -> Path:
    """Helper: create .agents/skills/<name>/SKILL.md with YAML frontmatter."""
    skill_dir = vault_path / ".agents" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    content = f"---\nname: {name}\ndescription: {desc}\n---\n{body}\n"
    skill_file.write_text(content)
    return skill_file


class TestDiscoverSkills:
    def test_discovers_multiple(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "greet", "Greet the user", "Say hello.")
        _make_skill(tmp_path, "deploy", "Deploy code", "Push to prod.")

        skills = discover_skills(tmp_path)
        assert len(skills) == 2
        names = {s.name for s in skills}
        assert names == {"greet", "deploy"}

    def test_empty_when_no_dir(self, tmp_path: Path) -> None:
        assert discover_skills(tmp_path) == []

    def test_skips_malformed(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "good", "Valid", "Works fine.")
        # Create a malformed SKILL.md (binary junk)
        bad_dir = tmp_path / ".agents" / "skills" / "bad"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_bytes(b"\x00\x01\x02\xff\xfe")

        skills = discover_skills(tmp_path)
        # At least the good skill should load; bad may or may not parse
        good_names = [s.name for s in skills if s.name == "good"]
        assert len(good_names) == 1


class TestLoadSkill:
    def test_load_existing(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "greet", "Greet", "Hello instructions")
        skill = load_skill(tmp_path, "greet")
        assert skill is not None
        assert skill.name == "greet"
        assert skill.description == "Greet"
        assert "Hello instructions" in skill.instructions

    def test_load_missing(self, tmp_path: Path) -> None:
        assert load_skill(tmp_path, "nonexistent") is None


class TestCheckVaultHealth:
    def test_all_present(self, tmp_path: Path) -> None:
        for f in ["AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md"]:
            (tmp_path / f).write_text("")
        assert check_vault_health(tmp_path) == []

    def test_missing_files(self, tmp_path: Path) -> None:
        (tmp_path / "AGENTS.md").write_text("")
        missing = check_vault_health(tmp_path)
        assert "SOUL.md" in missing
        assert "IDENTITY.md" in missing
        assert "USER.md" in missing
        assert "AGENTS.md" not in missing


class TestRecoverVault:
    @pytest.fixture()
    def git_repo(self, tmp_path: Path) -> VaultRepo:
        Repo.init(tmp_path)
        (tmp_path / "README.md").write_text("# vault\n")
        raw = Repo(tmp_path)
        raw.index.add(["README.md"])
        raw.index.commit("init")
        return VaultRepo(tmp_path)

    def test_clean_repo_no_recovery(self, git_repo: VaultRepo) -> None:
        assert recover_vault(git_repo) is False

    def test_dirty_repo_recovers(self, git_repo: VaultRepo) -> None:
        (git_repo.path / "README.md").write_text("dirty!")
        assert recover_vault(git_repo) is True
        assert git_repo.is_clean()
