"""Langfuse observability — v4 SDK with LangChain CallbackHandler.

``TracingManager`` encapsulates the Langfuse client lifecycle so tests can
create fresh instances without global state leaks. Module-level convenience
functions delegate to a default singleton for backward compat.
"""

from __future__ import annotations

import logging
from typing import Any

from commandclaw.config import Settings

log = logging.getLogger(__name__)


class TracingManager:
    """Per-instance Langfuse lifecycle — no global state."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any = None
        self._initialized = False

    def _ensure(self) -> bool:
        if self._initialized:
            return self._client is not None

        self._initialized = True

        if not self._settings.langfuse_public_key or not self._settings.langfuse_secret_key:
            log.warning("Langfuse keys not set — tracing disabled.")
            return False

        try:
            from langfuse import Langfuse

            self._client = Langfuse(
                public_key=self._settings.langfuse_public_key,
                secret_key=self._settings.langfuse_secret_key,
                host=self._settings.langfuse_host,
            )
            log.info("Langfuse v4 initialized (host=%s).", self._settings.langfuse_host)
            return True
        except ImportError:
            log.warning("langfuse package not installed — tracing disabled.")
            return False
        except Exception:
            log.exception("Failed to initialize Langfuse — tracing disabled.")
            return False

    @property
    def is_enabled(self) -> bool:
        return self._client is not None

    def create_handler(
        self,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> Any | None:
        """Create a Langfuse CallbackHandler for LangChain/LangGraph."""
        if not self._ensure():
            return None

        try:
            from langfuse.langchain import CallbackHandler

            handler = CallbackHandler()

            try:
                from langfuse import propagate_attributes

                propagate_attributes(
                    trace_name=self._settings.agent_id or "commandclaw",
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

    def flush(self) -> None:
        """Flush any pending Langfuse events. Call on shutdown."""
        if self._client is None:
            return
        try:
            self._client.flush()
            log.debug("Langfuse events flushed.")
        except Exception:
            log.exception("Error flushing Langfuse events.")


# ============================================================
# Default singleton + module-level convenience functions
# ============================================================

_default: TracingManager | None = None


def _default_manager(settings: Settings) -> TracingManager:
    global _default  # noqa: PLW0603
    if _default is None:
        _default = TracingManager(settings)
    return _default


def reset_default_manager() -> None:
    """Reset the default singleton. Useful in tests."""
    global _default  # noqa: PLW0603
    _default = None


def create_langfuse_handler(
    settings: Settings,
    session_id: str | None = None,
    user_id: str | None = None,
) -> Any | None:
    """Module-level convenience — delegates to the default manager."""
    return _default_manager(settings).create_handler(
        session_id=session_id, user_id=user_id,
    )


def flush_tracing() -> None:
    """Flush pending events on the default manager. Safe to call when uninitialized."""
    if _default is not None:
        _default.flush()
