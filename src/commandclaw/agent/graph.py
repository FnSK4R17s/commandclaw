"""CommandClaw agent — `langchain.agents.create_agent` with middleware guardrails.

Runtime context (vault path, agent identity, user/session IDs, API key) is passed
via the agent's `context_schema` rather than smuggled through `TypedDict` state.
Guardrails live as `@before_model` / `@after_model` middleware. Conversation
history persists through `AsyncSqliteSaver` so restarts don't drop threads.

Public surface:

* `CommandClawContext` — dataclass passed to every invocation
* `build_agent_graph(settings, checkpointer)` — returns a compiled agent
* `invoke_agent(agent, message, ...)` — wrapper returning `AgentResult`
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentState,
    ModelRequest,
    after_model,
    before_model,
    dynamic_prompt,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver

from commandclaw.config import Settings

log = logging.getLogger(__name__)


# ============================================================
# Runtime context — passed via create_agent(context_schema=...)
# ============================================================


@dataclass
class CommandClawContext:
    """Per-invocation runtime context. Lives in `runtime.context`, not state."""

    vault_path: str
    agent_id: str
    api_key: str | None = None
    user_id: str | None = None
    session_id: str | None = None


@dataclass
class AgentResult:
    """Result from a single agent invocation."""

    output: str
    success: bool
    error: str | None = None


# ============================================================
# Middleware — dynamic prompt + I/O guardrails
# ============================================================


@dynamic_prompt
def vault_identity_prompt(request: ModelRequest) -> str:
    """Assemble the system prompt from vault files for every model call."""
    ctx: CommandClawContext = request.runtime.context
    vault = Path(ctx.vault_path)

    parts: list[str] = [f"Your agent ID is {ctx.agent_id}."]
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


_BLOCK_INPUT = (
    "I can't process that — it may contain sensitive information. "
    "Please rephrase your request."
)
_BLOCK_OUTPUT = (
    "I drafted a response but it may contain sensitive information. "
    "Please rephrase your request."
)


@before_model(can_jump_to=["end"])
async def input_guardrails(state: AgentState, runtime: Any) -> dict[str, Any] | None:
    """Block jailbreak / PII / secrets in the latest user message."""
    from commandclaw.guardrails.engine import check_input

    msgs = state.get("messages", [])
    last = msgs[-1] if msgs else None
    if not isinstance(last, HumanMessage):
        return None

    content = last.content if isinstance(last.content, str) else str(last.content)
    ctx: CommandClawContext = runtime.context
    violations = await check_input(content, api_key=ctx.api_key)

    if violations:
        log.warning("Input guardrail violations: %s", violations)
        return {
            "messages": [AIMessage(content=_BLOCK_INPUT)],
            "jump_to": "end",
        }
    return None


@after_model
async def output_guardrails(state: AgentState, runtime: Any) -> dict[str, Any] | None:
    """Replace AI output if it leaks secrets / PII."""
    from commandclaw.guardrails.engine import check_output

    msgs = state.get("messages", [])
    last = msgs[-1] if msgs else None
    if not isinstance(last, AIMessage) or not last.content:
        return None

    content = last.content if isinstance(last.content, str) else str(last.content)
    ctx: CommandClawContext = runtime.context
    violations = await check_output(content, api_key=ctx.api_key)

    if violations:
        log.warning("Output guardrail violations: %s", violations)
        return {"messages": [AIMessage(content=_BLOCK_OUTPUT)]}
    return None


# ============================================================
# Graph builder
# ============================================================


def _build_llm(settings: Settings) -> ChatOpenAI:
    kwargs: dict[str, Any] = {
        "api_key": settings.openai_api_key,
        "model": settings.openai_model,
        "temperature": settings.openai_temperature,
        "max_tokens": settings.max_output_tokens,
    }
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return ChatOpenAI(**kwargs)


def _build_native_tools(settings: Settings) -> list[Any]:
    from commandclaw.agent.tools.bash_tool import create_bash_tool
    from commandclaw.agent.tools.file_delete import create_file_delete_tool
    from commandclaw.agent.tools.file_list import create_file_list_tool
    from commandclaw.agent.tools.file_read import create_file_read_tool
    from commandclaw.agent.tools.file_write import create_file_write_tool
    from commandclaw.agent.tools.skill_registry import (
        create_browse_skills_tool,
        create_install_skill_tool,
    )
    from commandclaw.agent.tools.system_info import create_system_info_tool
    from commandclaw.agent.tools.vault_memory import (
        create_memory_read_tool,
        create_memory_write_tool,
    )
    from commandclaw.agent.tools.vault_skill import (
        create_list_skills_tool,
        create_read_skill_tool,
    )
    from commandclaw.vault.git_ops import VaultRepo

    vault_path = settings.vault_path
    repo = VaultRepo(vault_path)
    repo.ensure_repo()

    return [
        create_bash_tool(vault_path, timeout=settings.bash_timeout),
        create_file_list_tool(vault_path),
        create_file_read_tool(vault_path),
        create_file_write_tool(vault_path),
        create_file_delete_tool(vault_path),
        create_memory_read_tool(vault_path),
        create_memory_write_tool(vault_path, repo),
        create_list_skills_tool(vault_path),
        create_read_skill_tool(vault_path),
        create_browse_skills_tool(),
        create_install_skill_tool(vault_path),
        create_system_info_tool(),
    ]


async def _maybe_load_mcp_tools(settings: Settings) -> tuple[list[Any], Any]:
    """Connect to MCP gateway and return (tools, client). Empty list on failure."""
    if not settings.mcp_gateway_url:
        return [], None

    from commandclaw.mcp import client as mcp_client_module
    from commandclaw.mcp.client import MCPClient
    from commandclaw.mcp.tools import create_mcp_tools

    client = MCPClient(
        gateway_url=settings.mcp_gateway_url,
        agent_id=settings.agent_id or "default",
        agent_key=settings.mcp_agent_key or "",
    )
    try:
        await client.connect()
        tools = await create_mcp_tools(client)
        log.info("Loaded %d MCP tool(s) from gateway", len(tools))
        return tools, client
    except (
        mcp_client_module.MCPGatewayUnavailable,
        mcp_client_module.MCPAgentNotEnrolled,
    ) as exc:
        log.warning("MCP unavailable — continuing without MCP tools: %s", exc)
        return [], None
    except Exception:
        log.exception("MCP tool loading failed — continuing without MCP tools")
        return [], None


async def build_agent_graph(
    settings: Settings,
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    model: BaseChatModel | None = None,
) -> tuple[Any, Any]:
    """Build the CommandClaw agent. Returns `(agent, mcp_client_or_None)`.

    The caller owns the checkpointer's lifecycle (open at startup, close at
    shutdown). MCP client is returned so the caller can `disconnect()` it.
    Pass ``model`` to inject a fake LLM (e.g. ``GenericFakeChatModel``) in tests.
    """
    llm = model if model is not None else _build_llm(settings)
    tools = _build_native_tools(settings)

    mcp_tools, mcp_client = await _maybe_load_mcp_tools(settings)
    tools.extend(mcp_tools)

    middleware = [
        vault_identity_prompt,
        input_guardrails,
        output_guardrails,
    ]

    agent = create_agent(
        model=llm,
        tools=tools,
        middleware=middleware,
        context_schema=CommandClawContext,
        checkpointer=checkpointer,
        name=settings.agent_id or "commandclaw",
    )

    log.info("Agent built: %d tools, model=%s", len(tools), settings.openai_model)
    return agent, mcp_client


# ============================================================
# Invocation wrapper — retries + tracing + structured result
# ============================================================


async def invoke_agent(
    agent: Any,
    message: str,
    settings: Settings,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
) -> AgentResult:
    """Invoke the agent on one message with retries + Langfuse tracing."""
    from commandclaw.tracing.langfuse_tracing import create_langfuse_handler

    context = CommandClawContext(
        vault_path=str(settings.vault_path),
        agent_id=settings.agent_id or "default",
        api_key=settings.openai_api_key,
        user_id=user_id,
        session_id=session_id,
    )
    thread_id = f"{context.agent_id}/{session_id or 'main'}"
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}

    handler = create_langfuse_handler(settings, session_id=session_id, user_id=user_id)
    if handler is not None:
        config["callbacks"] = [handler]

    last_error: str | None = None
    for attempt in range(settings.max_retries + 1):
        try:
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=message)]},
                config=config,
                context=context,
            )
            ai_msgs = [
                m for m in result.get("messages", [])
                if isinstance(m, AIMessage) and m.content
            ]
            output = ai_msgs[-1].content if ai_msgs else ""
            if isinstance(output, list):
                output = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in output
                )
            return AgentResult(output=output, success=True)

        except (KeyboardInterrupt, asyncio.CancelledError):
            raise
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < settings.max_retries:
                delay = settings.retry_base_delay * (2 ** attempt)
                log.warning(
                    "Agent invocation failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1,
                    settings.max_retries + 1,
                    last_error,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                log.exception("Agent invocation failed after %d attempt(s)", attempt + 1)

    return AgentResult(output="", success=False, error=last_error)
