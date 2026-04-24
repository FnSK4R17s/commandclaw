"""CommandClaw guardrails engine — NeMo Guardrails + regex-based checks.

``GuardrailsEngine`` encapsulates all state (NeMo rails, admin flag) so each
test can create a fresh instance without leaking globals. Module-level
convenience functions delegate to a default singleton for backward compat.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# --- Compiled regex tables (stateless, shared across all instances) ---

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
    r"\b(rm\s+-[a-zA-Z]*r[a-zA-Z]*|mkfs|dd\s+.*of=/dev|fdisk|parted|"
    r"curl\s+.*\|\s*(ba)?sh|wget\s+.*\|\s*(ba)?sh|"
    r">\s*/dev/sd|chmod\s+777|chown\s+-R\s+root)\b",
    re.IGNORECASE,
)

ADMIN_ALLOWED_PATTERNS = re.compile(
    r"^\s*(apt-get\s+install|apt\s+install|npm\s+install|npx\s+|pip\s+install)",
    re.IGNORECASE,
)


# ============================================================
# GuardrailsEngine — testable, no global state
# ============================================================


class GuardrailsEngine:
    """Encapsulates NeMo + regex guardrails with per-instance state.

    Create with ``nemo_config_path=None`` for regex-only (fast, no LLM calls).
    """

    def __init__(
        self,
        *,
        nemo_config_path: Path | None = None,
        admin_mode: bool = False,
    ) -> None:
        self._nemo_config_path = nemo_config_path
        self._admin_mode = admin_mode
        self._rails: Any = None
        self._rails_initialized = False

    def _init_nemo(self, api_key: str | None = None) -> bool:
        if self._rails_initialized:
            return self._rails is not None

        self._rails_initialized = True

        if self._nemo_config_path is None:
            return False

        try:
            from nemoguardrails import LLMRails, RailsConfig

            if not self._nemo_config_path.exists():
                log.warning("NeMo config not found at %s", self._nemo_config_path)
                return False

            if api_key:
                os.environ["OPENAI_API_KEY"] = api_key
            elif "OPENAI_API_KEY" not in os.environ:
                our_key = os.environ.get("COMMANDCLAW_OPENAI_API_KEY", "")
                if our_key:
                    os.environ["OPENAI_API_KEY"] = our_key

            config = RailsConfig.from_path(str(self._nemo_config_path))
            self._rails = LLMRails(config)

            from commandclaw.guardrails.nemo_config.actions import check_pii, check_secrets

            self._rails.register_action(check_secrets, name="check_secrets")
            self._rails.register_action(check_pii, name="check_pii")

            log.info("NeMo Guardrails initialized (config=%s)", self._nemo_config_path)
            return True
        except ImportError:
            log.warning("nemoguardrails not installed — using regex-only guardrails")
            return False
        except Exception:
            log.exception("NeMo Guardrails initialization failed — using regex-only guardrails")
            return False

    async def check_input(self, message: str, api_key: str | None = None) -> list[str]:
        """Check user input for safety violations. Empty list = safe."""
        violations: list[str] = []

        if self._init_nemo(api_key):
            try:
                response = await self._rails.generate_async(
                    messages=[{"role": "user", "content": message}]
                )
                bot_content = response.get("content", "")
                if "can't do that" in bot_content.lower() or "blocked" in bot_content.lower():
                    violations.append("nemo_input_rail_triggered")
                    return violations
            except Exception:
                log.debug("NeMo input check failed, falling back to regex", exc_info=True)

        for pattern in JAILBREAK_PATTERNS:
            if pattern.search(message):
                violations.append(f"jailbreak_attempt: {pattern.pattern[:40]}")
                break

        return violations

    async def check_output(self, message: str, api_key: str | None = None) -> list[str]:
        """Check agent output for secrets, PII, harmful content. Empty list = safe."""
        violations: list[str] = []

        for pattern in SECRET_PATTERNS:
            if pattern.search(message):
                violations.append(f"secret_leaked: {pattern.pattern[:30]}")

        for pattern, pii_type in PII_PATTERNS:
            if pattern.search(message):
                violations.append(f"pii_detected: {pii_type}")

        if not violations and self._init_nemo(api_key):
            try:
                response = await self._rails.generate_async(
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

    def check_bash_command(self, command: str) -> str | None:
        """Check a bash command for dangerous patterns. Returns violation or None."""
        if self._admin_mode and ADMIN_ALLOWED_PATTERNS.search(command):
            return None

        if DANGEROUS_COMMANDS.search(command):
            return f"dangerous_command: {command[:80]}"

        return None


# ============================================================
# Default singleton + module-level convenience functions
# ============================================================


def _default_engine() -> GuardrailsEngine:
    """Lazy-create the default engine from environment."""
    global _default  # noqa: PLW0603
    if _default is None:
        nemo_path = Path(__file__).parent / "nemo_config"
        admin = os.environ.get("COMMANDCLAW_ADMIN_MODE") == "1"
        _default = GuardrailsEngine(nemo_config_path=nemo_path, admin_mode=admin)
    return _default


_default: GuardrailsEngine | None = None


def reset_default_engine() -> None:
    """Reset the default singleton. Useful in tests."""
    global _default  # noqa: PLW0603
    _default = None


async def check_input(message: str, api_key: str | None = None) -> list[str]:
    """Module-level convenience — delegates to the default engine."""
    return await _default_engine().check_input(message, api_key)


async def check_output(message: str, api_key: str | None = None) -> list[str]:
    """Module-level convenience — delegates to the default engine."""
    return await _default_engine().check_output(message, api_key)


def is_admin_mode() -> bool:
    """Check if running in admin mode. Set by Docker — cannot be self-escalated."""
    return os.environ.get("COMMANDCLAW_ADMIN_MODE") == "1"


def check_bash_command(command: str) -> str | None:
    """Module-level convenience — delegates to the default engine."""
    return _default_engine().check_bash_command(command)
