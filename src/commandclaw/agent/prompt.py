"""Build the system prompt from vault state."""

from __future__ import annotations

from commandclaw.vault.agent_config import AgentConfig
from commandclaw.vault.identity import VaultIdentity
from commandclaw.vault.skills import Skill


def build_system_prompt(
    agent_config: AgentConfig,
    vault_identity: VaultIdentity,
    long_term_memory: str,
    daily_notes: dict[str, str],
    skills: list[Skill],
) -> str:
    """Assemble the full system prompt from vault components."""
    sections: list[str] = []

    # 1. AGENTS.md — workspace rules
    if agent_config.raw_text:
        sections.append(f"# Workspace Rules\n\n{agent_config.raw_text}")

    # 2. SOUL.md — who the agent is
    if vault_identity.soul:
        sections.append(f"# Soul\n\n{vault_identity.soul}")

    # 3. IDENTITY.md — structured identity
    ident = vault_identity.identity
    identity_parts: list[str] = []
    if ident.name:
        identity_parts.append(f"**Name:** {ident.name}")
    if ident.creature:
        identity_parts.append(f"**Creature:** {ident.creature}")
    if ident.vibe:
        identity_parts.append(f"**Vibe:** {ident.vibe}")
    if ident.emoji:
        identity_parts.append(f"**Emoji:** {ident.emoji}")
    if ident.origin:
        identity_parts.append(f"**Origin:** {ident.origin}")
    if identity_parts:
        sections.append("# Identity\n\n" + "\n".join(identity_parts))

    # 4. USER.md — who the human is
    if vault_identity.user:
        sections.append(f"# User\n\n{vault_identity.user}")

    # 5. TOOLS.md — local environment notes
    if vault_identity.tools:
        sections.append(f"# Tools & Environment\n\n{vault_identity.tools}")

    # 6. HEARTBEAT.md — recurring checks
    if vault_identity.heartbeat:
        sections.append(f"# Heartbeat\n\n{vault_identity.heartbeat}")

    # 7. Long-term memory
    if long_term_memory:
        sections.append(f"# Long-Term Memory\n\n{long_term_memory}")

    # 8. Recent daily notes (last 2 days, sorted newest first)
    if daily_notes:
        notes_parts: list[str] = []
        for day in sorted(daily_notes.keys(), reverse=True):
            notes_parts.append(f"## {day}\n\n{daily_notes[day]}")
        sections.append("# Recent Daily Notes\n\n" + "\n\n".join(notes_parts))

    # 9. Available skills (name + description only)
    if skills:
        skill_lines = [f"- **{s.name}**: {s.description}" for s in skills]
        sections.append(
            "# Available Skills\n\n"
            "Use the read_skill tool to load full instructions for a skill.\n\n"
            + "\n".join(skill_lines)
        )

    return "\n\n---\n\n".join(sections)
