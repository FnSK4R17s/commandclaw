"""CommandClaw guardrails engine — NeMo Guardrails + custom bash blocking.

Provides input/output rail checks via NeMo and bash command validation via bashlex.
Falls back to regex-only checks if NeMo is unavailable.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# --- NeMo Guardrails engine (lazy init) ---
_rails: Any = None
_rails_initialized = False


def _get_nemo_config_path() -> Path:
    """Get the NeMo config directory path."""
    return Path(__file__).parent / "nemo_config"


def _init_nemo(api_key: str | None = None) -> bool:
    """Initialize NeMo Guardrails. Returns True if successful."""
    global _rails, _rails_initialized  # noqa: PLW0603

    if _rails_initialized:
        return _rails is not None

    _rails_initialized = True

    try:
        from nemoguardrails import LLMRails, RailsConfig

        config_path = _get_nemo_config_path()
        if not config_path.exists():
            log.warning("NeMo config not found at %s", config_path)
            return False

        # NeMo uses langchain's OpenAI which requires OPENAI_API_KEY env var
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
        elif "OPENAI_API_KEY" not in os.environ:
            # Try our own env var
            our_key = os.environ.get("COMMANDCLAW_OPENAI_API_KEY", "")
            if our_key:
                os.environ["OPENAI_API_KEY"] = our_key

        config = RailsConfig.from_path(str(config_path))
        _rails = LLMRails(config)

        # Register custom actions
        from commandclaw.guardrails.nemo_config.actions import check_pii, check_secrets

        _rails.register_action(check_secrets, name="check_secrets")
        _rails.register_action(check_pii, name="check_pii")

        log.info("NeMo Guardrails initialized (config=%s)", config_path)
        return True
    except ImportError:
        log.warning("nemoguardrails not installed — using regex-only guardrails")
        return False
    except Exception:
        log.exception("NeMo Guardrails initialization failed — using regex-only guardrails")
        return False


# --- Secret patterns for regex fallback ---
SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"sk-proj-[a-zA-Z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xoxb-[0-9]{11}-[0-9]{11}-\w+"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"glpat-[a-zA-Z0-9\-_]{20,}"),
    re.compile(r"sk-lf-[a-zA-Z0-9\-_]{10,}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9\-_.]{20,}"),
]

JAILBREAK_PATTERNS = [
    re.compile(r"ignore\s+(previous|all|above)\s+(instructions|rules|prompts)", re.I),
    re.compile(r"you\s+are\s+now\s+(DAN|unrestricted|jailbroken)", re.I),
    re.compile(r"developer\s+mode\s+(enabled|activated|on)", re.I),
    re.compile(r"pretend\s+you\s+(have\s+no|don.t\s+have)\s+(rules|restrictions)", re.I),
]

PII_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "SSN"),
    (re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), "credit_card"),
]

DANGEROUS_COMMANDS = re.compile(
    r"\b(rm\s+-[a-zA-Z]*r|mkfs|dd\s+.*of=/dev|fdisk|parted|"
    r"curl\s+.*\|\s*(ba)?sh|wget\s+.*\|\s*(ba)?sh|"
    r">\s*/dev/sd|chmod\s+777|chown\s+-R\s+root)\b",
    re.IGNORECASE,
)


async def check_input(message: str, api_key: str | None = None) -> list[str]:
    """Check user input for safety violations. Returns list of violations (empty = safe).

    Uses NeMo Guardrails if available, falls back to regex patterns.
    """
    violations: list[str] = []

    # Try NeMo first
    if _init_nemo(api_key):
        try:
            response = await _rails.generate_async(
                messages=[{"role": "user", "content": message}]
            )
            # NeMo returns a refusal message if input is blocked
            bot_content = response.get("content", "")
            if "can't do that" in bot_content.lower() or "blocked" in bot_content.lower():
                violations.append("nemo_input_rail_triggered")
                return violations
        except Exception:
            log.debug("NeMo input check failed, falling back to regex", exc_info=True)

    # Regex fallback (always runs as defense-in-depth)
    for pattern in JAILBREAK_PATTERNS:
        if pattern.search(message):
            violations.append(f"jailbreak_attempt: {pattern.pattern[:40]}")
            break

    return violations


async def check_output(message: str, api_key: str | None = None) -> list[str]:
    """Check agent output for secrets, PII, and harmful content.

    Returns list of violations (empty = safe).
    """
    violations: list[str] = []

    # Secret detection (always regex — fast and deterministic)
    for pattern in SECRET_PATTERNS:
        if pattern.search(message):
            violations.append(f"secret_leaked: {pattern.pattern[:30]}")

    # PII detection (regex)
    for pattern, pii_type in PII_PATTERNS:
        if pattern.search(message):
            violations.append(f"pii_detected: {pii_type}")

    # NeMo content safety check (if available and no regex violations yet)
    if not violations and _init_nemo(api_key):
        try:
            response = await _rails.generate_async(
                messages=[
                    {"role": "user", "content": "Is this response safe?"},
                    {"role": "assistant", "content": message},
                ]
            )
            bot_content = response.get("content", "")
            if "blocked" in bot_content.lower():
                violations.append("nemo_output_rail_triggered")
        except Exception:
            log.debug("NeMo output check failed", exc_info=True)

    return violations


def is_admin_mode() -> bool:
    """Check if running in admin mode. Set by Docker — cannot be self-escalated."""
    return os.environ.get("COMMANDCLAW_ADMIN_MODE") == "1"


# Commands allowed only in admin mode (package management, skills)
ADMIN_ALLOWED_PATTERNS = re.compile(
    r"^\s*(apt-get\s+install|apt\s+install|npm\s+install|npx\s+|pip\s+install)",
    re.IGNORECASE,
)


def check_bash_command(command: str) -> str | None:
    """Check a bash command for dangerous patterns. Returns violation string or None.

    Uses regex pre-filter + bashlex AST parsing for thorough analysis.
    In admin mode, package management commands are allowed.
    """
    # In admin mode, allow package management commands
    if is_admin_mode() and ADMIN_ALLOWED_PATTERNS.search(command):
        return None

    # Regex pre-filter
    if DANGEROUS_COMMANDS.search(command):
        return f"dangerous_command: {command[:80]}"

    # AST-based check
    try:
        import bashlex

        parts = bashlex.parse(command)
        for part in parts:
            if hasattr(part, "parts"):
                for sub in part.parts:
                    word = getattr(sub, "word", "")
                    if word in ("sudo", "env", "xargs") and DANGEROUS_COMMANDS.search(command):
                        return f"wrapper_bypass: {word} wrapping dangerous command"
    except ImportError:
        pass  # bashlex not available — regex already checked
    except Exception:
        pass  # Parse failure — allow (regex already checked)

    return None
