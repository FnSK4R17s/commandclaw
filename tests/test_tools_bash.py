from __future__ import annotations

from pathlib import Path

from commandclaw.agent.tools.bash_tool import MAX_OUTPUT_LENGTH, create_bash_tool


def test_bash_runs_command_and_returns_output(tmp_path: Path) -> None:
    tool = create_bash_tool(tmp_path)
    result = tool.invoke({"command": "echo hello world"})
    assert result.strip() == "hello world"


def test_bash_nonzero_exit_code(tmp_path: Path) -> None:
    tool = create_bash_tool(tmp_path)
    result = tool.invoke({"command": "exit 42"})
    assert "[exit code 42]" in result


def test_bash_timeout_returns_error(tmp_path: Path) -> None:
    tool = create_bash_tool(tmp_path, timeout=1)
    result = tool.invoke({"command": "sleep 10"})
    assert "timed out" in result.lower()


def test_bash_output_truncation(tmp_path: Path) -> None:
    # Generate output longer than MAX_OUTPUT_LENGTH
    chars_needed = MAX_OUTPUT_LENGTH + 500
    tool = create_bash_tool(tmp_path)
    result = tool.invoke({"command": f"python3 -c \"print('x' * {chars_needed})\""})
    assert "[truncated" in result
    assert len(result) <= MAX_OUTPUT_LENGTH + 200  # truncation message adds a bit
