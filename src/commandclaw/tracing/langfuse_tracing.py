"""Langfuse observability — wraps LangChain agent runs with tracing."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from commandclaw.config import Settings

if TYPE_CHECKING:
    from langfuse.callback import CallbackHandler

log = logging.getLogger(__name__)

# Module-level reference so flush_tracing() can reach the client.
_langfuse_client: Any = None


def create_langfuse_handler(
    settings: Settings,
    session_id: str | None = None,
    user_id: str | None = None,
) -> CallbackHandler | None:
    """Create a Langfuse CallbackHandler for LangChain if credentials are configured.

    Returns ``None`` when Langfuse is not configured (keys missing) or when the
    ``langfuse`` package is not installed.  Errors during handler creation are
    caught so tracing failures never crash the agent.
    """
    global _langfuse_client  # noqa: PLW0603

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        log.warning("Langfuse keys not set — tracing disabled.")
        return None

    try:
        from langfuse.callback import CallbackHandler as LangfuseCallbackHandler
    except ImportError:
        log.warning("langfuse package not installed — tracing disabled.")
        return None

    try:
        handler = LangfuseCallbackHandler(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            session_id=session_id,
            user_id=user_id,
            trace_name="commandclaw-agent",
        )
        # Keep a reference to the underlying Langfuse client for flushing.
        _langfuse_client = handler.langfuse
        log.debug("Langfuse tracing handler created (session=%s).", session_id)
        return handler  # type: ignore[return-value]
    except Exception:
        log.exception("Failed to create Langfuse handler — tracing disabled.")
        return None


def flush_tracing() -> None:
    """Flush any pending Langfuse events.  Call on shutdown."""
    if _langfuse_client is None:
        return
    try:
        _langfuse_client.flush()
        log.debug("Langfuse events flushed.")
    except Exception:
        log.exception("Error flushing Langfuse events.")
