"""Agent hatching — identity collection and vault bootstrapping."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, field_validator


class HatchIdentity(BaseModel):
    """Agent identity fields collected during hatching."""

    name: str
    emoji: str = ""
    creature: str = ""
    vibe: str = ""

    @field_validator("name")
    @classmethod
    def name_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name is required")
        return v.strip()


def collect_hatch_input(
    agent_id: str,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[..., None] = print,
) -> tuple[HatchIdentity, str] | None:
    """Interactive prompts to collect identity + user intro.

    Returns ``(identity, intro)`` or ``None`` if cancelled.
    ``input_fn`` / ``print_fn`` are injectable for testing.
    """
    print_fn(f"\nHatching agent: {agent_id}\n")
    try:
        name = input_fn("  Name your agent: ").strip()
        while not name:
            name = input_fn("  Name is required: ").strip()
        emoji = input_fn("  Signature emoji (optional): ").strip()
        creature = input_fn(
            "  Creature type — AI / robot / familiar / ghost / etc (optional): "
        ).strip()
        vibe = input_fn("  Vibe — personality in a word or two (optional): ").strip()

        identity = HatchIdentity(name=name, emoji=emoji, creature=creature, vibe=vibe)

        print_fn("\nTell your agent about yourself — who you are, what you do,")
        print_fn("what you want this agent to help with.\n")
        intro = input_fn("hatch> ").strip()

        return identity, intro
    except (EOFError, KeyboardInterrupt):
        print_fn("\nHatch cancelled.")
        return None


def write_identity_file(vault_path: Path, identity: HatchIdentity) -> None:
    """Write the user-provided identity fields into IDENTITY.md."""
    content = (
        "# IDENTITY.md - Who Am I?\n"
        "\n"
        f"- **Name:** {identity.name}\n"
        f"- **Creature:** {identity.creature or '(choose your own)'}\n"
        f"- **Vibe:** {identity.vibe or '(choose your own)'}\n"
        f"- **Emoji:** {identity.emoji or '(choose your own)'}\n"
        "- **Avatar:** (path or URL)\n"
        "\n"
        "## Origin\n"
        "\n"
        "_(Write your origin story here. Who are you? What shaped you?"
        " This is your identity — make it yours.)_\n"
    )
    (vault_path / "IDENTITY.md").write_text(content)
