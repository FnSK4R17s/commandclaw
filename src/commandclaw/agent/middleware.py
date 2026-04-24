"""LangChain middleware — dynamic prompt + I/O guardrails.

Raw logic lives in plain functions (``_build_prompt``, ``_check_input``,
``_check_output``) that are independently testable. The ``@dynamic_prompt``,
``@before_model``, and ``@after_model`` decorators wrap them for the agent.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain.agents.middleware import (
    AgentState,
    ModelRequest,
    after_model,
    before_model,
    dynamic_prompt,
)
from langchain_core.messages import AIMessage, HumanMessage

from commandclaw.agent.context import CommandClawContext

log = logging.getLogger(__name__)

_BLOCK_INPUT = (
    "I can't process that — it may contain sensitive information. "
    "Please rephrase your request."
)
_BLOCK_OUTPUT = (
    "I drafted a response but it may contain sensitive information. "
    "Please rephrase your request."
)


# ============================================================
# Raw logic — testable without the agent framework
# ============================================================


def build_identity_prompt(vault_path: str, agent_id: str) -> str:
    """Assemble the system prompt from vault files."""
    vault = Path(vault_path)

    parts: list[str] = [f"Your agent ID is {agent_id}."]
    for filename in ("IDENTITY.md", "AGENTS.md", "USER.md"):
        p = vault / filename
        if p.exists():
            text = p.read_text(encoding="utf-8").strip()
            if text:
                parts.append(text)
    parts.append(
        "Use your tools to accomplish tasks. "
        "Use file_read to access other vault files. "
        "Use file_write or memory_write to persist important context."
    )
    return "\n\n".join(parts)


async def check_input_message(
    state: dict[str, Any], ctx: CommandClawContext,
) -> dict[str, Any] | None:
    """Check the latest user message for safety violations.

    Returns a jump-to-end dict if blocked, ``None`` if clean.
    """
    from commandclaw.guardrails.engine import check_input

    msgs = state.get("messages", [])
    last = msgs[-1] if msgs else None
    if not isinstance(last, HumanMessage):
        return None

    content = last.content if isinstance(last.content, str) else str(last.content)
    violations = await check_input(content, api_key=ctx.api_key)

    if violations:
        log.warning("Input guardrail violations: %s", violations)
        return {
            "messages": [AIMessage(content=_BLOCK_INPUT)],
            "jump_to": "end",
        }
    return None


async def check_output_message(
    state: dict[str, Any], ctx: CommandClawContext,
) -> dict[str, Any] | None:
    """Check the latest AI message for leaked secrets / PII.

    Returns a replacement dict if blocked, ``None`` if clean.
    """
    from commandclaw.guardrails.engine import check_output

    msgs = state.get("messages", [])
    last = msgs[-1] if msgs else None
    if not isinstance(last, AIMessage) or not last.content:
        return None

    content = last.content if isinstance(last.content, str) else str(last.content)
    violations = await check_output(content, api_key=ctx.api_key)

    if violations:
        log.warning("Output guardrail violations: %s", violations)
        return {"messages": [AIMessage(content=_BLOCK_OUTPUT)]}
    return None


# ============================================================
# Decorated middleware — wired into create_agent(middleware=[...])
# ============================================================


@dynamic_prompt
def vault_identity_prompt(request: ModelRequest) -> str:
    """Assemble the system prompt from vault files for every model call."""
    ctx: CommandClawContext = request.runtime.context
    return build_identity_prompt(ctx.vault_path, ctx.agent_id)


@before_model(can_jump_to=["end"])
async def input_guardrails(state: AgentState, runtime: Any) -> dict[str, Any] | None:
    """Block jailbreak / PII / secrets in the latest user message."""
    return await check_input_message(state, runtime.context)


@after_model
async def output_guardrails(state: AgentState, runtime: Any) -> dict[str, Any] | None:
    """Replace AI output if it leaks secrets / PII."""
    return await check_output_message(state, runtime.context)
