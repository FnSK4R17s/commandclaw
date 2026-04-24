"""Integration tests for ``commandclaw.vault.workspace``.

These touch the filesystem and ``git`` so they're integration-tier. Each test
points the module-level ``_WORKSPACES_DIR`` at ``tmp_path`` to keep the host
home directory untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

from commandclaw.vault import workspace as ws

pytestmark = pytest.mark.integration


@pytest.fixture
def workspaces_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the module-level workspaces dir to a tmp location."""
    target = tmp_path / "workspaces"
    monkeypatch.setattr(ws, "_WORKSPACES_DIR", target)
    return target


@pytest.fixture
def template(tmp_path: Path) -> Path:
    """A minimal vault template with one tracked file."""
    template = tmp_path / "template"
    template.mkdir()
    (template / "AGENTS.md").write_text("# Workspace Rules\n")
    (template / "IDENTITY.md").write_text("# Identity\n")
    return template


def test_create_workspace_clones_template_and_inits_git(
    workspaces_dir: Path, template: Path
) -> None:
    agent_id, ws_path = ws.create_workspace(template, agent_id="brave-fox-0001")

    assert agent_id == "brave-fox-0001"
    assert ws_path == workspaces_dir / "brave-fox-0001"
    assert (ws_path / "AGENTS.md").read_text() == "# Workspace Rules\n"
    assert (ws_path / ".git").is_dir()

    repo = Repo(ws_path)
    assert not repo.bare
    head = repo.head.commit
    assert "brave-fox-0001" in head.message


def test_create_workspace_strips_template_git_dir(
    workspaces_dir: Path, template: Path
) -> None:
    """The template's own .git must not be copied — only the new init repo lives."""
    Repo.init(template)
    (template / ".git" / "HEAD").write_text("template-marker\n")

    _agent_id, ws_path = ws.create_workspace(template, agent_id="calm-owl-0002")
    assert (ws_path / ".git" / "HEAD").read_text().strip() != "template-marker"


def test_create_workspace_is_idempotent_on_existing_id(
    workspaces_dir: Path, template: Path
) -> None:
    ws.create_workspace(template, agent_id="cool-bat-0003")
    (workspaces_dir / "cool-bat-0003" / "marker.txt").write_text("kept")

    agent_id, ws_path = ws.create_workspace(template, agent_id="cool-bat-0003")
    assert agent_id == "cool-bat-0003"
    assert (ws_path / "marker.txt").read_text() == "kept"


def test_create_workspace_generates_id_when_omitted(
    workspaces_dir: Path, template: Path
) -> None:
    agent_id, ws_path = ws.create_workspace(template)
    assert ws_path.parent == workspaces_dir
    assert agent_id == ws_path.name


def test_create_workspace_raises_when_template_missing(
    workspaces_dir: Path, tmp_path: Path
) -> None:
    with pytest.raises(FileNotFoundError, match="Vault template not found"):
        ws.create_workspace(tmp_path / "nope")


def test_list_workspaces_returns_empty_when_dir_absent(workspaces_dir: Path) -> None:
    assert ws.list_workspaces() == []


def test_list_workspaces_enumerates_dirs(
    workspaces_dir: Path, template: Path
) -> None:
    ws.create_workspace(template, agent_id="a-fox-0001")
    ws.create_workspace(template, agent_id="b-owl-0002")
    entries = ws.list_workspaces()
    ids = [e["agent_id"] for e in entries]
    assert ids == ["a-fox-0001", "b-owl-0002"]


def test_delete_workspace_removes_dir(
    workspaces_dir: Path, template: Path
) -> None:
    _id, ws_path = ws.create_workspace(template, agent_id="del-rat-0005")
    assert ws_path.exists()

    assert ws.delete_workspace("del-rat-0005") is True
    assert not ws_path.exists()


def test_delete_workspace_returns_false_when_missing(workspaces_dir: Path) -> None:
    assert ws.delete_workspace("never-existed-9999") is False
