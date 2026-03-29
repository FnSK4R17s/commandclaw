"""Memory read/write — long-term MEMORY.md and daily session notes."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from commandclaw.vault.git_ops import VaultRepo

logger = logging.getLogger(__name__)

_MEMORY_DIR = "memory"


def read_long_term_memory(vault_path: Path) -> str:
    """Read MEMORY.md from the vault root."""
    memory_file = vault_path / "MEMORY.md"
    if not memory_file.exists():
        return ""
    return memory_file.read_text(encoding="utf-8")


def read_daily_notes(vault_path: Path, days: int = 2) -> dict[str, str]:
    """Read daily notes for the last *days* days (today + previous)."""
    memory_dir = vault_path / _MEMORY_DIR
    notes: dict[str, str] = {}
    today = date.today()
    for offset in range(days):
        day = today - timedelta(days=offset)
        day_str = day.isoformat()
        note_path = memory_dir / f"{day_str}.md"
        if note_path.exists():
            notes[day_str] = note_path.read_text(encoding="utf-8")
    return notes


def write_daily_note(vault_path: Path, entry: str, repo: VaultRepo) -> Path:
    """Append a timestamped entry to today's daily note and commit."""
    memory_dir = vault_path / _MEMORY_DIR
    memory_dir.mkdir(parents=True, exist_ok=True)

    today_str = date.today().isoformat()
    note_path = memory_dir / f"{today_str}.md"

    timestamp = datetime.now(tz=timezone.utc).strftime("%H:%M UTC")
    line = f"\n- [{timestamp}] {entry}\n"

    with note_path.open("a", encoding="utf-8") as f:
        f.write(line)

    rel_path = str(note_path.relative_to(vault_path))
    repo.commit(f"memory: daily note {today_str}", paths=[rel_path])
    logger.info("Wrote daily note: %s", rel_path)
    return note_path


def update_long_term_memory(
    vault_path: Path, section: str, entry: str, repo: VaultRepo
) -> None:
    """Append *entry* under *section* (e.g. '## Decisions') in MEMORY.md and commit."""
    memory_file = vault_path / "MEMORY.md"
    text = memory_file.read_text(encoding="utf-8") if memory_file.exists() else ""

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    new_line = f"\n- [{timestamp}] {entry}"

    header = f"## {section}"
    if header in text:
        # Insert right after the section header line
        idx = text.index(header) + len(header)
        # Find end of that header line
        newline_idx = text.find("\n", idx)
        if newline_idx == -1:
            text += new_line
        else:
            text = text[: newline_idx + 1] + new_line + text[newline_idx + 1 :]
    else:
        # Section doesn't exist — append it
        text += f"\n\n{header}\n{new_line}\n"

    memory_file.write_text(text, encoding="utf-8")

    rel_path = str(memory_file.relative_to(vault_path))
    repo.commit(f"memory: update {section}", paths=[rel_path])
    logger.info("Updated long-term memory section '%s'", section)
