"""Tests for commandclaw.vault.memory — long-term and daily notes."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from git import Repo

from commandclaw.vault.git_ops import VaultRepo
from commandclaw.vault.memory import (
    read_daily_notes,
    read_long_term_memory,
    update_long_term_memory,
    write_daily_note,
)


@pytest.fixture()
def vault(tmp_path: Path) -> tuple[Path, VaultRepo]:
    """A vault path backed by a real git repo with an initial commit."""
    Repo.init(tmp_path)
    (tmp_path / "README.md").write_text("# vault\n")
    raw = Repo(tmp_path)
    raw.index.add(["README.md"])
    raw.index.commit("init")
    return tmp_path, VaultRepo(tmp_path)


class TestReadLongTermMemory:
    def test_existing_memory(self, tmp_path: Path) -> None:
        (tmp_path / "MEMORY.md").write_text("## Decisions\n- chose X")
        assert "chose X" in read_long_term_memory(tmp_path)

    def test_missing_memory(self, tmp_path: Path) -> None:
        assert read_long_term_memory(tmp_path) == ""


class TestReadDailyNotes:
    def test_reads_todays_note(self, tmp_path: Path) -> None:
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        today_str = date.today().isoformat()
        (mem_dir / f"{today_str}.md").write_text("- did stuff")

        notes = read_daily_notes(tmp_path, days=1)
        assert today_str in notes
        assert "did stuff" in notes[today_str]

    def test_no_notes(self, tmp_path: Path) -> None:
        assert read_daily_notes(tmp_path, days=3) == {}


class TestWriteDailyNote:
    def test_creates_and_commits(self, vault: tuple[Path, VaultRepo]) -> None:
        vault_path, repo = vault
        note_path = write_daily_note(vault_path, "test entry", repo)

        assert note_path.exists()
        assert "test entry" in note_path.read_text()
        # Should have been committed
        assert repo.is_clean()

    def test_appends_to_existing(self, vault: tuple[Path, VaultRepo]) -> None:
        vault_path, repo = vault
        write_daily_note(vault_path, "first", repo)
        write_daily_note(vault_path, "second", repo)

        today_str = date.today().isoformat()
        content = (vault_path / "memory" / f"{today_str}.md").read_text()
        assert "first" in content
        assert "second" in content


class TestUpdateLongTermMemory:
    def test_creates_new_section(self, vault: tuple[Path, VaultRepo]) -> None:
        vault_path, repo = vault
        update_long_term_memory(vault_path, "Decisions", "chose Python", repo)

        text = (vault_path / "MEMORY.md").read_text()
        assert "## Decisions" in text
        assert "chose Python" in text
        assert repo.is_clean()

    def test_appends_to_existing_section(
        self, vault: tuple[Path, VaultRepo]
    ) -> None:
        vault_path, repo = vault
        (vault_path / "MEMORY.md").write_text("## Decisions\n")
        repo.commit("seed memory")

        update_long_term_memory(vault_path, "Decisions", "chose Rust", repo)
        text = (vault_path / "MEMORY.md").read_text()
        assert "chose Rust" in text
