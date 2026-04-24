from __future__ import annotations

from pathlib import Path

from commandclaw.agent.tools.file_delete import create_file_delete_tool
from commandclaw.agent.tools.file_list import create_file_list_tool
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


# --- file_delete tests ---


def test_file_delete_removes_file(tmp_path: Path) -> None:
    (tmp_path / "doomed.txt").write_text("bye")
    tool = create_file_delete_tool(tmp_path)
    result = tool.invoke({"file_path": "doomed.txt"})
    assert "Deleted" in result
    assert not (tmp_path / "doomed.txt").exists()


def test_file_delete_missing_file(tmp_path: Path) -> None:
    tool = create_file_delete_tool(tmp_path)
    result = tool.invoke({"file_path": "ghost.txt"})
    assert "Error" in result
    assert "not found" in result


def test_file_delete_rejects_directory(tmp_path: Path) -> None:
    (tmp_path / "subdir").mkdir()
    tool = create_file_delete_tool(tmp_path)
    result = tool.invoke({"file_path": "subdir"})
    assert "Error" in result
    assert "not a regular file" in result


def test_file_delete_rejects_path_outside_vault(tmp_path: Path) -> None:
    tool = create_file_delete_tool(tmp_path)
    result = tool.invoke({"file_path": "../../etc/passwd"})
    assert "Error" in result
    assert "outside the vault" in result


# --- file_list tests ---


def test_file_list_shows_entries(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "sub").mkdir()
    tool = create_file_list_tool(tmp_path)
    result = tool.invoke({"directory": "."})
    assert "a.txt" in result
    assert "b.txt" in result
    assert "sub/" in result


def test_file_list_subdirectory(tmp_path: Path) -> None:
    sub = tmp_path / "notes"
    sub.mkdir()
    (sub / "one.md").write_text("note")
    tool = create_file_list_tool(tmp_path)
    result = tool.invoke({"directory": "notes"})
    assert "one.md" in result


def test_file_list_empty_directory(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    tool = create_file_list_tool(tmp_path)
    result = tool.invoke({"directory": "empty"})
    assert "empty directory" in result


def test_file_list_missing_directory(tmp_path: Path) -> None:
    tool = create_file_list_tool(tmp_path)
    result = tool.invoke({"directory": "nope"})
    assert "Error" in result
    assert "not found" in result


def test_file_list_rejects_file_as_dir(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("x")
    tool = create_file_list_tool(tmp_path)
    result = tool.invoke({"directory": "file.txt"})
    assert "Error" in result
    assert "not a directory" in result


def test_file_list_rejects_path_outside_vault(tmp_path: Path) -> None:
    tool = create_file_list_tool(tmp_path)
    result = tool.invoke({"directory": "../../etc"})
    assert "Error" in result
    assert "outside the vault" in result
