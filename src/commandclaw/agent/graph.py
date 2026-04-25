"""CommandClaw agent — build and invoke the LangChain v1 agent graph.

Public surface:

* ``build_agent_graph(settings, checkpointer)`` — returns a compiled agent
* ``invoke_agent(agent, message, ...)`` — wrapper returning ``AgentResult``

Data types live in ``context.py``; middleware lives in ``middleware.py``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver

from commandclaw.agent.context import AgentResult, CommandClawContext
from commandclaw.agent.middleware import (
    input_guardrails,
    output_guardrails,
    vault_identity_prompt,
)
from commandclaw.config import Settings

log = logging.getLogger(__name__)


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
        mcp_client_module.MCPGatewayUnavailableError,
        mcp_client_module.MCPAgentNotEnrolledError,
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
    """Build the CommandClaw agent. Returns ``(agent, mcp_client_or_None)``.

    The caller owns the checkpointer's lifecycle (open at startup, close at
    shutdown). MCP client is returned so the caller can ``disconnect()`` it.
    Pass ``model`` to inject a fake LLM (e.g. ``GenericFakeChatModel``) in tests.
    """
    from langchain.agents import create_agent

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
    abort_event: asyncio.Event | None = None,
) -> AgentResult:
    """Invoke the agent on one message with retries + Langfuse tracing."""
    from commandclaw.tracing.langfuse_tracing import create_langfuse_handler

    if abort_event is not None and abort_event.is_set():
        raise asyncio.CancelledError

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
        if abort_event is not None and abort_event.is_set():
            raise asyncio.CancelledError
        try:
            task = asyncio.create_task(
                agent.ainvoke(
                    {"messages": [HumanMessage(content=message)]},
                    config=config,
                    context=context,
                )
            )
            if abort_event is not None:
                abort_task = asyncio.create_task(abort_event.wait())
                done, pending = await asyncio.wait(
                    {task, abort_task}, return_when=asyncio.FIRST_COMPLETED
                )
                for p in pending:
                    p.cancel()
                    try:
                        await p
                    except asyncio.CancelledError:
                        pass
                if task not in done:
                    raise asyncio.CancelledError
                result = task.result()
            else:
                result = await task
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
