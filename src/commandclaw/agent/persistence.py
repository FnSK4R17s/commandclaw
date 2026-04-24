"""Async SQLite checkpointer wired to the vault.

`AsyncSqliteSaver` needs a live `aiosqlite.Connection` whose lifetime matches
the agent's. We expose `open_checkpointer(settings)` that returns the saver
plus an async `close()` callback. Callers own the lifecycle (open at startup,
close in `post_shutdown`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from commandclaw.config import Settings

log = logging.getLogger(__name__)


def _resolve_db_path(settings: Settings) -> Path:
    if settings.checkpoint_db is not None:
        return settings.checkpoint_db
    if settings.vault_path is None:
        raise RuntimeError("vault_path must be set before opening the checkpointer")
    return settings.vault_path / ".commandclaw" / "checkpoints.db"


async def open_checkpointer(
    settings: Settings,
) -> tuple[AsyncSqliteSaver, Callable[[], Coroutine[Any, Any, None]]]:
    """Open the SQLite checkpointer. Returns `(saver, close_coro)`."""
    db_path = _resolve_db_path(settings)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = await aiosqlite.connect(str(db_path))
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    log.info("Checkpointer ready at %s", db_path)

    async def close() -> None:
        try:
            await conn.close()
            log.debug("Checkpointer connection closed")
        except Exception:
            log.exception("Error closing checkpointer connection")

    return saver, close
