from __future__ import annotations

from pathlib import Path

from commandclaw.agent.tools.file_read import create_file_read_tool
from commandclaw.agent.tools.file_write import create_file_write_tool

# --- file_read tests ---


def test_file_read_reads_file(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("contents here", encoding="utf-8")
    tool = create_file_read_tool(tmp_path)
    result = tool.invoke({"file_path": "hello.txt"})
    assert result == "contents here"


def test_file_read_rejects_path_outside_vault(tmp_path: Path) -> None:
    tool = create_file_read_tool(tmp_path)
    result = tool.invoke({"file_path": "../../etc/passwd"})
    assert "Error" in result
    assert "outside the vault" in result


def test_file_read_handles_missing_file(tmp_path: Path) -> None:
    tool = create_file_read_tool(tmp_path)
    result = tool.invoke({"file_path": "nonexistent.txt"})
    assert "Error" in result
    assert "not found" in result


# --- file_write tests ---


def test_file_write_creates_file(tmp_path: Path) -> None:
    tool = create_file_write_tool(tmp_path)
    result = tool.invoke({"file_path": "output.txt", "content": "hello"})
    assert "Wrote" in result
    assert (tmp_path / "output.txt").read_text(encoding="utf-8") == "hello"


def test_file_write_creates_parent_dirs(tmp_path: Path) -> None:
    tool = create_file_write_tool(tmp_path)
    result = tool.invoke({"file_path": "sub/dir/file.txt", "content": "nested"})
    assert "Wrote" in result
    assert (tmp_path / "sub" / "dir" / "file.txt").read_text(encoding="utf-8") == "nested"


def test_file_write_rejects_path_outside_vault(tmp_path: Path) -> None:
    tool = create_file_write_tool(tmp_path)
    result = tool.invoke({"file_path": "../../../tmp/evil.txt", "content": "bad"})
    assert "Error" in result
    assert "outside the vault" in result
