"""CommandClaw agent runtime — LangChain AgentExecutor."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from commandclaw.config import Settings

log = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Result from a single agent invocation."""

    output: str
    success: bool
    error: str | None = None


async def create_agent(
    settings: Settings,
) -> tuple[Any, Callable[[], Coroutine[Any, Any, None]]]:
    """Build the LangChain agent + tools. Returns (agent_executor, cleanup_fn).

    This is called ONCE at startup. The agent_executor is reused across invocations.
    """
    from langchain.agents import AgentExecutor, create_openai_tools_agent
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_openai import ChatOpenAI

    from commandclaw.agent.tools.bash_tool import create_bash_tool
    from commandclaw.agent.tools.file_read import create_file_read_tool
    from commandclaw.agent.tools.file_write import create_file_write_tool
    from commandclaw.agent.tools.vault_memory import (
        create_memory_read_tool,
        create_memory_write_tool,
    )
    from commandclaw.agent.tools.vault_skill import (
        create_list_skills_tool,
        create_read_skill_tool,
    )
    from commandclaw.mcp.client import MCPClient
    from commandclaw.mcp.tools import create_mcp_tools
    from commandclaw.vault.git_ops import VaultRepo
    from commandclaw.vault.recovery import check_vault_health, recover_vault

    # --- Vault setup ---
    vault_path = settings.vault_path
    repo = VaultRepo(vault_path)
    repo.ensure_repo()

    missing = check_vault_health(vault_path)
    if missing:
        log.warning("Vault missing files: %s", ", ".join(missing))
    recover_vault(repo)

    # --- Native tools ---
    tools: list[Any] = [
        create_bash_tool(vault_path, timeout=settings.bash_timeout),
        create_file_read_tool(vault_path),
        create_file_write_tool(vault_path),
        create_memory_read_tool(vault_path),
        create_memory_write_tool(vault_path, repo),
        create_list_skills_tool(vault_path),
        create_read_skill_tool(vault_path),
    ]
    log.info("Created %d native tool(s)", len(tools))

    # --- MCP tools (optional) ---
    mcp_client: MCPClient | None = None
    if settings.mcp_gateway_url and settings.mcp_agent_key:
        try:
            mcp_client = MCPClient(
                gateway_url=settings.mcp_gateway_url,
                agent_key=settings.mcp_agent_key,
            )
            await mcp_client.connect()
            mcp_tools = await create_mcp_tools(mcp_client)
            tools.extend(mcp_tools)
            log.info("Added %d MCP tool(s)", len(mcp_tools))
        except Exception:
            log.exception("MCP setup failed — continuing without MCP tools")
            mcp_client = None

    # --- LLM ---
    llm_kwargs: dict[str, Any] = {
        "api_key": settings.openai_api_key,
        "model": settings.openai_model,
        "temperature": settings.openai_temperature,
    }
    if settings.openai_base_url:
        llm_kwargs["base_url"] = settings.openai_base_url
    llm = ChatOpenAI(**llm_kwargs)

    # --- Agent ---
    prompt = ChatPromptTemplate.from_messages([
        ("system", "{system_prompt}"),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])

    agent = create_openai_tools_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=False,
        handle_parsing_errors=True,
        max_iterations=25,
    )

    # --- Cleanup ---
    async def cleanup() -> None:
        if mcp_client is not None:
            try:
                await mcp_client.disconnect()
            except Exception:
                log.debug("Error disconnecting MCP client", exc_info=True)
        try:
            from commandclaw.tracing.langfuse_tracing import flush_tracing

            flush_tracing()
        except Exception:
            log.debug("Error flushing tracing", exc_info=True)

    log.info(
        "Agent created with %d tool(s), model=%s", len(tools), settings.openai_model
    )
    return agent_executor, cleanup


async def invoke_agent(
    agent_executor: Any,
    message: str,
    settings: Settings,
    session_id: str | None = None,
    user_id: str | None = None,
) -> AgentResult:
    """Run the agent on a single user message. Fresh vault read each time."""
    from commandclaw.agent.prompt import build_system_prompt
    from commandclaw.tracing.langfuse_tracing import create_langfuse_handler
    from commandclaw.vault.agent_config import load_agent_config
    from commandclaw.vault.identity import load_identity
    from commandclaw.vault.memory import read_daily_notes, read_long_term_memory
    from commandclaw.vault.skills import discover_skills

    vault_path = settings.vault_path

    try:
        # Fresh vault state
        agent_config = load_agent_config(vault_path)
        identity = load_identity(vault_path)
        memory = read_long_term_memory(vault_path)
        daily = read_daily_notes(vault_path)
        skills = discover_skills(vault_path)

        system_prompt = build_system_prompt(
            agent_config=agent_config,
            vault_identity=identity,
            long_term_memory=memory,
            daily_notes=daily,
            skills=skills,
        )

        # Tracing callback (may be None)
        callbacks: list[Any] = []
        langfuse_handler = create_langfuse_handler(settings, session_id, user_id)
        if langfuse_handler is not None:
            callbacks.append(langfuse_handler)

        # Invoke
        config: dict[str, Any] = {}
        if callbacks:
            config["callbacks"] = callbacks

        result = await agent_executor.ainvoke(
            {"input": message, "system_prompt": system_prompt},
            config=config,
        )

        return AgentResult(output=result.get("output", ""), success=True)

    except KeyboardInterrupt:
        raise
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.exception("Agent invocation failed")
        return AgentResult(
            output="",
            success=False,
            error=f"{type(exc).__name__}: {exc}",
        )
