"""Custom NeMo Guardrails actions for CommandClaw."""

import re

from nemoguardrails.actions import action

# Secret patterns — same as graph.py but registered as NeMo actions
SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"sk-proj-[a-zA-Z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xoxb-[0-9]{11}-[0-9]{11}-\w+"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"glpat-[a-zA-Z0-9\-_]{20,}"),
    re.compile(r"sk-lf-[a-zA-Z0-9\-_]{10,}"),
    re.compile(r"pk-lf-[a-zA-Z0-9\-_]{10,}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9\-_.]{20,}"),
]

PII_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "SSN"),
    (re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), "credit_card"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "email"),
]


@action(is_system_action=True)
async def check_secrets(context: dict | None = None) -> bool:
    """Check bot response for leaked secrets. Returns True if safe."""
    bot_message = (context or {}).get("bot_message", "")
    for pattern in SECRET_PATTERNS:
        if pattern.search(bot_message):
            return False
    return True


@action(is_system_action=True)
async def check_pii(context: dict | None = None) -> bool:
    """Check bot response for PII. Returns True if safe."""
    bot_message = (context or {}).get("bot_message", "")
    for pattern, _ in PII_PATTERNS:
        if pattern.search(bot_message):
            return False
    return True
