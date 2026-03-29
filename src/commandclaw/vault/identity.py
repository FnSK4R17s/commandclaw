"""Parse IDENTITY.md and load companion vault files (SOUL, USER, TOOLS, HEARTBEAT)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Identity:
    """Structured fields parsed from IDENTITY.md key-value pairs."""

    name: str = ""
    creature: str = ""
    vibe: str = ""
    emoji: str = ""
    avatar: str = ""
    origin: str = ""


@dataclass
class VaultIdentity:
    """Full identity bundle: structured identity + raw companion files."""

    identity: Identity = field(default_factory=Identity)
    soul: str = ""
    user: str = ""
    tools: str = ""
    heartbeat: str = ""


_KV_PATTERN = re.compile(r"^-\s+\*\*(\w+):\*\*\s*(.+)$", re.MULTILINE)


def _parse_identity_md(text: str) -> Identity:
    """Extract key-value pairs and Origin section from IDENTITY.md content."""
    fields: dict[str, str] = {}
    for match in _KV_PATTERN.finditer(text):
        key = match.group(1).lower()
        fields[key] = match.group(2).strip()

    origin = ""
    origin_match = re.search(r"## Origin\s*\n(.*)", text, re.DOTALL)
    if origin_match:
        origin = origin_match.group(1).strip()

    return Identity(
        name=fields.get("name", ""),
        creature=fields.get("creature", ""),
        vibe=fields.get("vibe", ""),
        emoji=fields.get("emoji", ""),
        avatar=fields.get("avatar", ""),
        origin=origin,
    )


def _read_optional(path: Path) -> str:
    """Read a file, returning empty string if it doesn't exist."""
    if not path.exists():
        logger.debug("Optional file missing: %s", path)
        return ""
    return path.read_text(encoding="utf-8")


def load_identity(vault_path: Path) -> VaultIdentity:
    """Load all identity-related vault files."""
    identity_text = _read_optional(vault_path / "IDENTITY.md")
    identity = _parse_identity_md(identity_text) if identity_text else Identity()

    return VaultIdentity(
        identity=identity,
        soul=_read_optional(vault_path / "SOUL.md"),
        user=_read_optional(vault_path / "USER.md"),
        tools=_read_optional(vault_path / "TOOLS.md"),
        heartbeat=_read_optional(vault_path / "HEARTBEAT.md"),
    )
