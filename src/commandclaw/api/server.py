"""Uvicorn runner for the CommandClaw API server."""

from __future__ import annotations

from commandclaw.config import Settings


def run_server(settings: Settings) -> None:
    """Start the uvicorn server. Blocking."""
    import uvicorn

    uvicorn.run(
        "commandclaw.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )
