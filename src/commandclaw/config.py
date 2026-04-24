"""Centralised configuration loaded from environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime config lives here — one source of truth."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="COMMANDCLAW_",
        extra="ignore",
    )

    # --- Vault ---
    vault_path: Path | None = Field(
        default=None,
        description="Explicit vault path. If unset, workspace manager assigns one.",
    )
    vault_template: Path = Field(
        default=Path("/apps/commandclaw-vault"),
        description="Path to the vault template repo (commandclaw-vault).",
    )
    agent_id: str = Field(
        default="default",
        description="Agent identity — used for workspace naming (cclaw-<agent-id>-<uuid>).",
    )
    reuse_workspace: bool = Field(
        default=True,
        description="Reuse the latest workspace for this agent_id, or create fresh each time.",
    )

    # --- LLM ---
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key (or Codex OAuth access token).",
    )
    openai_model: str = Field(
        default="gpt-5.4-mini",
        description="OpenAI model to use for the agent.",
    )
    openai_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    openai_base_url: str | None = Field(
        default=None,
        description="Optional custom base URL for the OpenAI API.",
    )

    # --- Telegram ---
    telegram_bot_token: str = Field(
        default="",
        description="Telegram bot token from @BotFather.",
    )
    telegram_allowed_chat_ids: list[int] = Field(
        default_factory=list,
        description="Chat IDs allowed to interact. Empty = allow all.",
    )
    telegram_chunk_size: int = Field(
        default=4000,
        description="Max characters per Telegram message before chunking.",
    )

    # --- MCP Gateway ---
    mcp_gateway_url: str | None = Field(
        default=None,
        description="URL of the commandclaw-mcp gateway (e.g. http://localhost:8100).",
    )
    mcp_agent_key: str | None = Field(
        default=None,
        description="Rotating agent key for the MCP gateway.",
    )

    # --- Langfuse ---
    langfuse_public_key: str | None = Field(default=None)
    langfuse_secret_key: str | None = Field(default=None)
    langfuse_host: str = Field(default="https://cloud.langfuse.com")

    # --- Execution ---
    bash_timeout: int = Field(
        default=120,
        description="Default timeout in seconds for bash tool commands.",
    )
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_base_delay: float = Field(
        default=1.0,
        description="Base delay in seconds for exponential backoff.",
    )
    max_output_tokens: int = Field(
        default=16_384,
        description="Cap on model max_tokens. Override per-deploy for large-context models.",
    )

    # --- Persistence ---
    checkpoint_db: Path | None = Field(
        default=None,
        description=(
            "SQLite path for the LangGraph checkpointer. "
            "Defaults to <vault>/.commandclaw/checkpoints.db when None."
        ),
    )

    # --- Codex credential shortcut ---
    codex_home: Path = Field(
        default=Path.home() / ".codex",
        description="Path to Codex CLI home directory for credential reading.",
    )
