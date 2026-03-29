"""Retry wrapper with exponential backoff."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from commandclaw.agent.runtime import AgentResult, invoke_agent
from commandclaw.config import Settings

log = logging.getLogger(__name__)


async def invoke_with_retry(
    agent_executor: Any,
    message: str,
    settings: Settings,
    session_id: str | None = None,
    user_id: str | None = None,
) -> AgentResult:
    """Invoke the agent with exponential backoff retries.

    Uses settings.max_retries (default 3) and settings.retry_base_delay (default 1.0).
    """
    max_retries: int = settings.max_retries
    base_delay: float = settings.retry_base_delay
    last_result: AgentResult | None = None

    for attempt in range(max_retries + 1):
        result = await invoke_agent(
            agent_executor=agent_executor,
            message=message,
            settings=settings,
            session_id=session_id,
            user_id=user_id,
        )

        if result.success:
            return result

        last_result = result

        if attempt < max_retries:
            delay = base_delay * (2 ** attempt)
            log.warning(
                "Agent invocation failed (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1,
                max_retries + 1,
                result.error,
                delay,
            )
            try:
                await asyncio.sleep(delay)
            except (KeyboardInterrupt, asyncio.CancelledError):
                log.info("Retry interrupted")
                return result
        else:
            log.error(
                "Agent invocation failed after %d attempt(s): %s",
                max_retries + 1,
                result.error,
            )

    # Should not be reachable, but satisfy the type checker
    assert last_result is not None
    return last_result
