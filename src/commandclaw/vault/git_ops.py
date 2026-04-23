"""Git operations for the vault repo."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from git import InvalidGitRepositoryError, Repo

logger = logging.getLogger(__name__)


class VaultRepo:
    """Thin wrapper around a git repo that IS the agent vault."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.repo = Repo(path)
        except InvalidGitRepositoryError:
            logger.warning("Not a git repo: %s — will init on ensure_repo()", path)
            self.repo = None  # type: ignore[assignment]

    def ensure_repo(self) -> None:
        """git init if the vault path is not already a repo."""
        if self.repo is not None:
            return
        logger.info("Initialising git repo at %s", self.path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.repo = Repo.init(self.path)

    def commit(self, message: str, paths: list[str] | None = None) -> str:
        """Stage files and commit. Returns the commit SHA."""
        if paths:
            self.repo.index.add(paths)
        else:
            self.repo.git.add(A=True)

        if not self.repo.index.diff("HEAD") and not self.repo.untracked_files:
            logger.debug("Nothing to commit.")
            return self.repo.head.commit.hexsha

        commit = self.repo.index.commit(message)
        logger.info("Committed %s: %s", commit.hexsha[:8], message)
        return commit.hexsha

    def discard(self) -> None:
        """Discard all uncommitted changes (git checkout -- .)."""
        self.repo.git.checkout("--", ".")
        logger.info("Discarded uncommitted changes in %s", self.path)

    def log(self, n: int = 10) -> list[dict[str, str]]:
        """Return the *n* most recent commits."""
        commits: list[dict[str, str]] = []
        for c in self.repo.iter_commits(max_count=n):
            commits.append(
                {
                    "sha": c.hexsha,
                    "message": c.message.strip(),
                    "author": str(c.author),
                    "timestamp": datetime.fromtimestamp(
                        c.committed_date, tz=UTC
                    ).isoformat(),
                }
            )
        return commits

    def is_clean(self) -> bool:
        """True when there are no uncommitted changes."""
        return not self.repo.is_dirty(untracked_files=True)
