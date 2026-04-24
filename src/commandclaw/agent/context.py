"""Pure data types for the CommandClaw agent — no framework dependencies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CommandClawContext:
    """Per-invocation runtime context. Lives in ``runtime.context``, not state."""

    vault_path: str
    agent_id: str
    api_key: str | None = None
    user_id: str | None = None
    session_id: str | None = None


@dataclass
class AgentResult:
    """Result from a single agent invocation."""

    output: str
    success: bool
    error: str | None = None
