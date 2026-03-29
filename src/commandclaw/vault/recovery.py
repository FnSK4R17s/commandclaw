"""Git-based vault recovery and health checks."""

from __future__ import annotations

import logging
from pathlib import Path

from commandclaw.vault.git_ops import VaultRepo

logger = logging.getLogger(__name__)

_REQUIRED_FILES = ["AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md"]


def recover_vault(repo: VaultRepo) -> bool:
    """Discard uncommitted changes if the vault is dirty. Returns True if recovery was needed."""
    if repo.is_clean():
        return False
    logger.warning("Vault is dirty — discarding uncommitted changes")
    repo.discard()
    return True


def check_vault_health(vault_path: Path) -> list[str]:
    """Return a list of missing required files."""
    missing: list[str] = []
    for filename in _REQUIRED_FILES:
        if not (vault_path / filename).exists():
            missing.append(filename)
    if missing:
        logger.warning("Missing vault files: %s", ", ".join(missing))
    return missing
