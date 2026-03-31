"""Langfuse observability — v4 SDK with LangChain CallbackHandler."""

from __future__ import annotations

import logging
from typing import Any

from commandclaw.config import Settings

log = logging.getLogger(__name__)

_langfuse_client: Any = None
_initialized = False


def _ensure_langfuse(settings: Settings) -> bool:
    """Initialize the Langfuse singleton once. Returns True if ready."""
    global _langfuse_client, _initialized  # noqa: PLW0603

    if _initialized:
        return _langfuse_client is not None

    _initialized = True

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        log.warning("Langfuse keys not set — tracing disabled.")
        return False

    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        log.info("Langfuse v4 initialized (host=%s).", settings.langfuse_host)
        return True
    except ImportError:
        log.warning("langfuse package not installed — tracing disabled.")
        return False
    except Exception:
        log.exception("Failed to initialize Langfuse — tracing disabled.")
        return False


def create_langfuse_handler(
    settings: Settings,
    session_id: str | None = None,
    user_id: str | None = None,
) -> Any | None:
    """Create a Langfuse CallbackHandler for LangChain/LangGraph.

    In v4, session_id and user_id are propagated via context, not constructor args.
    The trace name is set to the agent_id so each agent is identifiable in the UI.
    """
    if not _ensure_langfuse(settings):
        return None

    try:
        from langfuse.langchain import CallbackHandler

        handler = CallbackHandler()

        # v4: propagate attributes — agent_id as trace name for multi-agent filtering
        try:
            from langfuse import propagate_attributes

            propagate_attributes(
                trace_name=settings.agent_id or "commandclaw",
                session_id=session_id,
                user_id=user_id,
                tags=["commandclaw"],
            )
        except ImportError:
            pass

        return handler
    except Exception:
        log.exception("Failed to create Langfuse handler.")
        return None


def flush_tracing() -> None:
    """Flush any pending Langfuse events. Call on shutdown."""
    if _langfuse_client is None:
        return
    try:
        _langfuse_client.flush()
        log.debug("Langfuse events flushed.")
    except Exception:
        log.exception("Error flushing Langfuse events.")
