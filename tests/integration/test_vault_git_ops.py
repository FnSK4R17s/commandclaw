"""Tests for commandclaw.vault.git_ops — VaultRepo wrapper."""

from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

from commandclaw.vault.git_ops import VaultRepo


pytestmark = pytest.mark.integration


@pytest.fixture()
def git_repo(tmp_path: Path) -> VaultRepo:
    """Create a real git repo with an initial commit so HEAD exists."""
    Repo.init(tmp_path)
    # Create an initial commit so HEAD is valid
    readme = tmp_path / "README.md"
    readme.write_text("# Vault\n")
    raw = Repo(tmp_path)
    raw.index.add(["README.md"])
    raw.index.commit("initial commit")
    return VaultRepo(tmp_path)


class TestVaultRepoInit:
    def test_init_on_real_repo(self, git_repo: VaultRepo) -> None:
        assert git_repo.repo is not None
        assert git_repo.path.exists()

    def test_init_on_non_repo(self, tmp_path: Path) -> None:
        """Non-repo path sets repo to None."""
        plain_dir = tmp_path / "not_a_repo"
        plain_dir.mkdir()
        vr = VaultRepo(plain_dir)
        assert vr.repo is None


class TestEnsureRepo:
    def test_ensure_repo_creates_repo(self, tmp_path: Path) -> None:
        target = tmp_path / "new_vault"
        target.mkdir()
        vr = VaultRepo(target)
        assert vr.repo is None

        vr.ensure_repo()
        assert vr.repo is not None
        assert (target / ".git").is_dir()

    def test_ensure_repo_idempotent(self, git_repo: VaultRepo) -> None:
        repo_before = git_repo.repo
        git_repo.ensure_repo()
        assert git_repo.repo is repo_before


class TestCommit:
    def test_commit_returns_sha(self, git_repo: VaultRepo) -> None:
        (git_repo.path / "file.txt").write_text("hello")
        sha = git_repo.commit("add file")
        assert isinstance(sha, str)
        assert len(sha) == 40

    def test_commit_specific_paths(self, git_repo: VaultRepo) -> None:
        (git_repo.path / "a.txt").write_text("a")
        (git_repo.path / "b.txt").write_text("b")
        sha = git_repo.commit("add a only", paths=["a.txt"])
        # b.txt should still be untracked
        assert git_repo.repo.untracked_files == ["b.txt"]
        assert len(sha) == 40

    def test_commit_nothing_returns_head(self, git_repo: VaultRepo) -> None:
        head_sha = git_repo.repo.head.commit.hexsha
        sha = git_repo.commit("no-op")
        assert sha == head_sha


class TestIsClean:
    def test_clean_repo(self, git_repo: VaultRepo) -> None:
        assert git_repo.is_clean() is True

    def test_dirty_repo(self, git_repo: VaultRepo) -> None:
        (git_repo.path / "dirty.txt").write_text("change")
        assert git_repo.is_clean() is False


class TestLog:
    def test_log_returns_commits(self, git_repo: VaultRepo) -> None:
        (git_repo.path / "f.txt").write_text("data")
        git_repo.commit("second commit")

        entries = git_repo.log(n=5)
        assert len(entries) == 2
        assert entries[0]["message"] == "second commit"
        assert "sha" in entries[0]
        assert "timestamp" in entries[0]

    def test_log_respects_n(self, git_repo: VaultRepo) -> None:
        for i in range(5):
            (git_repo.path / f"f{i}.txt").write_text(str(i))
            git_repo.commit(f"commit {i}")

        assert len(git_repo.log(n=3)) == 3


class TestDiscard:
    def test_discard_removes_changes(self, git_repo: VaultRepo) -> None:
        tracked = git_repo.path / "README.md"
        tracked.write_text("modified!")
        assert git_repo.is_clean() is False

        git_repo.discard()
        assert tracked.read_text() == "# Vault\n"
