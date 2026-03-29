from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from commandclaw.agent.retry import invoke_with_retry
from commandclaw.agent.runtime import AgentResult


@dataclass
class _FakeSettings:
    max_retries: int = 2
    retry_base_delay: float = 0.0  # no real delay in tests


@pytest.mark.asyncio
async def test_invoke_with_retry_returns_on_success() -> None:
    ok = AgentResult(output="done", success=True, error=None)
    mock_invoke = AsyncMock(return_value=ok)

    with patch("commandclaw.agent.retry.invoke_agent", mock_invoke):
        result = await invoke_with_retry(
            agent_executor=object(),
            message="hi",
            settings=_FakeSettings(),  # type: ignore[arg-type]
        )

    assert result.success is True
    assert result.output == "done"
    mock_invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_invoke_with_retry_retries_then_returns_error() -> None:
    fail = AgentResult(output="", success=False, error="boom")
    mock_invoke = AsyncMock(return_value=fail)

    settings = _FakeSettings(max_retries=2, retry_base_delay=0.0)

    with patch("commandclaw.agent.retry.invoke_agent", mock_invoke):
        result = await invoke_with_retry(
            agent_executor=object(),
            message="hi",
            settings=settings,  # type: ignore[arg-type]
        )

    assert result.success is False
    assert result.error == "boom"
    # initial attempt + 2 retries = 3 total calls
    assert mock_invoke.await_count == 3


@pytest.mark.asyncio
async def test_invoke_with_retry_succeeds_on_second_attempt() -> None:
    fail = AgentResult(output="", success=False, error="transient")
    ok = AgentResult(output="recovered", success=True, error=None)
    mock_invoke = AsyncMock(side_effect=[fail, ok])

    settings = _FakeSettings(max_retries=3, retry_base_delay=0.0)

    with patch("commandclaw.agent.retry.invoke_agent", mock_invoke):
        result = await invoke_with_retry(
            agent_executor=object(),
            message="hi",
            settings=settings,  # type: ignore[arg-type]
        )

    assert result.success is True
    assert result.output == "recovered"
    assert mock_invoke.await_count == 2
