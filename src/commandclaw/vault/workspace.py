"""Workspace-per-agent manager — clone vault template, one workspace per session.

Naming convention follows chakravarti-cli's adjective-animal-NNNN pattern.
The agent ID IS the workspace name — they're the same thing.

  Agent ID / Workspace: brave-panda-4821

Workspaces live at ~/.commandclaw/workspaces/<agent-id>/
Each workspace is a full Git-backed vault clone from commandclaw-vault template.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import time
from pathlib import Path

from git import Repo

logger = logging.getLogger(__name__)

_WORKSPACES_DIR = Path.home() / ".commandclaw" / "workspaces"
_DEFAULT_TEMPLATE = Path("/apps/commandclaw-vault")

_ADJECTIVES = [
    "bold", "brave", "calm", "cool", "crisp", "deft", "fair", "fast", "fine", "firm",
    "fond", "free", "glad", "gold", "good", "keen", "kind", "lean", "live", "neat",
    "nice", "pure", "rare", "rich", "safe", "sage", "slim", "soft", "sure", "tall",
    "tidy", "true", "vast", "warm", "wide", "wild", "wise", "zany", "epic", "swift",
]

_ANIMALS = [
    "ape", "bat", "bear", "bison", "boar", "bull", "civet", "cobra", "crane", "crow",
    "deer", "dove", "eagle", "fox", "frog", "gaur", "gecko", "goat", "hawk", "hare",
    "heron", "ibis", "jackal", "kite", "koel", "langur", "lion", "moth", "mongoose",
    "myna", "newt", "otter", "owl", "panda", "peacock", "rat", "rhino", "robin",
    "shrew", "stork", "tiger", "viper", "wolf",
]


def generate_agent_id() -> str:
    """Generate a memorable agent ID: adjective-animal-NNNN."""
    ns = int(time.time() * 1_000_000_000)
    h = int(hashlib.sha256(str(ns).encode()).hexdigest(), 16)

    adj = _ADJECTIVES[h % len(_ADJECTIVES)]
    animal = _ANIMALS[(h >> 16) % len(_ANIMALS)]
    suffix = (h >> 32) % 10000

    if adj == "holy":
        animal = "cow"

    return f"{adj}-{animal}-{suffix:04}"


def list_workspaces() -> list[dict[str, str]]:
    """List all workspaces. Returns list of dicts with: agent_id, path."""
    if not _WORKSPACES_DIR.exists():
        return []

    return [
        {"agent_id": entry.name, "path": str(entry)}
        for entry in sorted(_WORKSPACES_DIR.iterdir())
        if entry.is_dir()
    ]


def create_workspace(
    template_path: Path | None = None,
    agent_id: str | None = None,
) -> tuple[str, Path]:
    """Create a new workspace from the vault template. Returns (agent_id, path).

    If agent_id is provided and already exists, returns the existing workspace.
    If agent_id is None, generates a new one.
    """
    template = template_path or _DEFAULT_TEMPLATE
    if not template.exists():
        raise FileNotFoundError(
            f"Vault template not found at {template}. "
            "Set COMMANDCLAW_VAULT_TEMPLATE or clone commandclaw-vault."
        )

    if agent_id is None:
        agent_id = generate_agent_id()

    ws_path = _WORKSPACES_DIR / agent_id
    if ws_path.exists():
        logger.info("Reusing workspace: %s", agent_id)
        return agent_id, ws_path

    _WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)

    shutil.copytree(template, ws_path, ignore=shutil.ignore_patterns(".git"))

    repo = Repo.init(ws_path)
    repo.git.add(A=True)
    repo.index.commit(f"init: {agent_id} from commandclaw-vault template")

    logger.info("Created workspace: %s", agent_id)
    return agent_id, ws_path


def delete_workspace(agent_id: str) -> bool:
    """Delete a workspace. Returns True if deleted."""
    ws_path = _WORKSPACES_DIR / agent_id
    if not ws_path.exists():
        return False
    if not str(ws_path).startswith(str(_WORKSPACES_DIR)):
        raise ValueError(f"Refusing to delete path outside workspaces dir: {ws_path}")
    shutil.rmtree(ws_path)
    logger.info("Deleted workspace: %s", agent_id)
    return True
