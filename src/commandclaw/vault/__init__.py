"""Vault — Git-backed agent state: config, identity, memory, skills."""

from __future__ import annotations

from commandclaw.vault.agent_config import AgentConfig, load_agent_config
from commandclaw.vault.git_ops import VaultRepo
from commandclaw.vault.identity import Identity, VaultIdentity, load_identity
from commandclaw.vault.memory import (
    read_daily_notes,
    read_long_term_memory,
    update_long_term_memory,
    write_daily_note,
)
from commandclaw.vault.recovery import check_vault_health, recover_vault
from commandclaw.vault.skills import Skill, discover_skills, load_skill

__all__ = [
    "AgentConfig",
    "Identity",
    "Skill",
    "VaultIdentity",
    "VaultRepo",
    "check_vault_health",
    "discover_skills",
    "load_agent_config",
    "load_identity",
    "load_skill",
    "read_daily_notes",
    "read_long_term_memory",
    "recover_vault",
    "update_long_term_memory",
    "write_daily_note",
]
