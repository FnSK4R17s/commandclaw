"""CommandClaw agent graph — LangGraph StateGraph with guardrails and memory.

Replaces the prompt-heavy runtime with code-structural behavior:
- Pre-processing nodes for memory loading and session classification
- NeMo Guardrails for input/output safety (jailbreak, PII, secrets)
- Regex-based dangerous-command blocking for tool execution
- Checkpointer for conversation history
- ~50 token system prompt (identity only)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from typing_extensions import TypedDict

from commandclaw.config import Settings

log = logging.getLogger(__name__)


# ============================================================
# State and Context
# ============================================================


class CommandClawState(TypedDict):
    """Typed state flowing through the agent graph."""

    messages: Annotated[list, add_messages]
    session_type: str
    trigger_source: str
    user_id: str
    agent_id: str
    memory_loaded: bool
    vault_context: list[str]
    guardrail_violations: list[str]
    identity_prompt: str


@dataclass
class CommandClawContext:
    """Runtime context injected at invocation — not part of graph state."""

    user_id: str
    agent_id: str
    vault_path: str
    settings: Settings | None = None


# ============================================================
# Graph Nodes
# ============================================================


async def load_identity(state: CommandClawState) -> dict[str, Any]:
    """Load agent identity from vault IDENTITY.md for the system prompt."""
    vault_path = Path(state.get("_vault_path", "/workspace"))
    identity_file = vault_path / "IDENTITY.md"

    identity = ""
    if identity_file.exists():
        identity = identity_file.read_text(encoding="utf-8").strip()

    # Load AGENTS.md and USER.md into the prompt alongside identity
    agents_file = vault_path / "AGENTS.md"
    user_file = vault_path / "USER.md"
    agents_md = agents_file.read_text(encoding="utf-8").strip() if agents_file.exists() else ""
    user_md = user_file.read_text(encoding="utf-8").strip() if user_file.exists() else ""

    agent_id = state.get("agent_id", "commandclaw")

    # Build system prompt: agent_id + identity + workspace instructions + user context
    parts = [f"Your agent ID is {agent_id}."]
    if identity:
        parts.append(identity)
    if agents_md:
        parts.append(agents_md)
    if user_md:
        parts.append(user_md)
    parts.append(
        "Use your tools to accomplish tasks. "
        "Use file_read to access other workspace files when needed. "
        "Use file_write or memory_write to persist important context."
    )
    prompt = "\n\n".join(parts)

    return {"identity_prompt": prompt, "memory_loaded": True}


async def input_guardrails(state: CommandClawState) -> dict[str, Any]:
    """Check user input via NeMo Guardrails + regex fallback.

    Returns ONLY new violations for this turn (replaces accumulated list).
    Traced as a guardrail span in Langfuse when a parent trace is active.
    """
    from commandclaw.guardrails.engine import check_input

    last_msg = state["messages"][-1] if state["messages"] else None
    if not last_msg or not isinstance(last_msg, HumanMessage):
        return {"guardrail_violations": []}

    content = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
    api_key = state.get("_api_key")

    # Trace as a guardrail span
    try:
        from langfuse import get_client as get_langfuse

        lf = get_langfuse()
        with lf.start_as_current_observation(
            name="input_guardrails",
            as_type="guardrail",
            input={"message": content[:500]},
        ) as span:
            violations = await check_input(content, api_key=api_key)
            passed = len(violations) == 0
            span.update(
                output={"passed": passed, "violations": violations},
                level="WARNING" if violations else "DEFAULT",
            )
    except Exception:
        violations = await check_input(content, api_key=api_key)

    if violations:
        log.warning("Input guardrail violations: %s", violations)

    return {"guardrail_violations": violations}


async def output_guardrails(state: CommandClawState) -> dict[str, Any]:
    """Scan agent output via NeMo Guardrails + regex for secrets and PII.

    Traced as a guardrail span in Langfuse when a parent trace is active.
    """
    from commandclaw.guardrails.engine import check_output

    ai_messages = [m for m in state.get("messages", []) if isinstance(m, AIMessage) and m.content]
    if not ai_messages:
        return {"guardrail_violations": []}

    content = ai_messages[-1].content
    if not isinstance(content, str):
        content = str(content)

    api_key = state.get("_api_key")

    # Trace as a guardrail span
    try:
        from langfuse import get_client as get_langfuse

        lf = get_langfuse()
        with lf.start_as_current_observation(
            name="output_guardrails",
            as_type="guardrail",
            input={"message": content[:500]},
        ) as span:
            violations = await check_output(content, api_key=api_key)
            passed = len(violations) == 0
            span.update(
                output={"passed": passed, "violations": violations},
                level="WARNING" if violations else "DEFAULT",
            )
    except Exception:
        violations = await check_output(content, api_key=api_key)

    if violations:
        log.warning("Output guardrail violations: %s", violations)

    return {"guardrail_violations": violations}


def route_guardrail_result(state: CommandClawState) -> Literal["end", "block"]:
    """Route based on guardrail violations."""
    if state.get("guardrail_violations"):
        return "block"
    return "end"


async def block_and_notify(state: CommandClawState) -> dict[str, Any]:
    """Replace the last AI message with a safety notice."""
    violations = state.get("guardrail_violations", [])
    log.warning("Guardrail violations: %s", violations)

    block_msg = AIMessage(
        content="I can't share that — it may contain sensitive information. "
        "Please rephrase your request."
    )
    return {"messages": [block_msg]}


# ============================================================
# Graph Builder
# ============================================================


def build_agent_graph(settings: Settings) -> Any:
    """Build the CommandClaw agent graph with guardrails and memory.

    Returns a compiled LangGraph that can be invoked with:
        graph.ainvoke(
            {"messages": [...], "trigger_source": "user", ...},
            config={"configurable": {"thread_id": "agent-id/session-id"}}
        )
    """
    # --- LLM ---
    # Model-specific max output tokens — don't exceed model limits
    model_name = settings.openai_model or ""
    if "5.4-mini" in model_name or "gpt-5" in model_name:
        max_tokens = 128_000
    elif "4.1-mini" in model_name or "4o-mini" in model_name:
        max_tokens = 32_000
    elif "o1" in model_name or "o3" in model_name or "o4" in model_name:
        max_tokens = 100_000
    else:
        max_tokens = 16_384  # Safe default

    llm_kwargs: dict[str, Any] = {
        "api_key": settings.openai_api_key,
        "model": settings.openai_model,
        "temperature": settings.openai_temperature,
        "max_tokens": max_tokens,
    }
    if settings.openai_base_url:
        llm_kwargs["base_url"] = settings.openai_base_url
    llm = ChatOpenAI(**llm_kwargs)

    # --- Tools ---
    from commandclaw.agent.tools.bash_tool import create_bash_tool
    from commandclaw.agent.tools.file_delete import create_file_delete_tool
    from commandclaw.agent.tools.file_list import create_file_list_tool
    from commandclaw.agent.tools.file_read import create_file_read_tool
    from commandclaw.agent.tools.file_write import create_file_write_tool
    from commandclaw.agent.tools.vault_memory import (
        create_memory_read_tool,
        create_memory_write_tool,
    )
    from commandclaw.agent.tools.skill_registry import (
        create_browse_skills_tool,
        create_install_skill_tool,
    )
    from commandclaw.agent.tools.system_info import create_system_info_tool
    from commandclaw.agent.tools.vault_skill import (
        create_list_skills_tool,
        create_read_skill_tool,
    )
    from commandclaw.vault.git_ops import VaultRepo

    vault_path = settings.vault_path
    repo = VaultRepo(vault_path)
    repo.ensure_repo()

    tools: list[Any] = [
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

    # --- MCP Gateway tools (lazy-loaded on first invocation) ---
    # Uses raw httpx JSON-RPC — no anyio, no MCP SDK transport.
    _mcp_client = None
    _mcp_client_module = None
    if settings.mcp_gateway_url:
        from commandclaw.mcp import client as _mcp_client_module
        from commandclaw.mcp.client import MCPClient

        _mcp_client = MCPClient(
            gateway_url=settings.mcp_gateway_url,
            agent_id=settings.agent_id or "default",
            agent_key=settings.mcp_agent_key or "",
        )
        log.info("MCP gateway configured at %s (tools loaded on first invocation)", settings.mcp_gateway_url)

    _mcp_loaded = False
    _mcp_lock = asyncio.Lock()

    # --- Langfuse tracing ---
    from commandclaw.tracing.langfuse_tracing import create_langfuse_handler

    langfuse_handler = create_langfuse_handler(settings)

    # --- Inner agent (ReAct loop) ---
    # The inner agent handles tool calling. The outer graph handles
    # pre/post processing, guardrails, and routing.
    inner_agent = create_react_agent(llm, tools)

    # --- Outer graph ---
    async def run_agent(state: CommandClawState) -> dict[str, Any]:
        """Run the inner ReAct agent with the identity prompt injected."""
        nonlocal inner_agent, _mcp_loaded

        # Lazy MCP tool discovery — runs once on first invocation
        if _mcp_client and not _mcp_loaded:
            async with _mcp_lock:
                if not _mcp_loaded:  # Double-check after acquiring lock
                    try:
                        from commandclaw.mcp.tools import create_mcp_tools

                        await _mcp_client.connect()
                        mcp_tools = await create_mcp_tools(_mcp_client)
                        tools.extend(mcp_tools)
                        inner_agent = create_react_agent(llm, tools)
                        log.info("Loaded %d MCP tool(s) from gateway", len(mcp_tools))
                    except (
                        _mcp_client_module.MCPGatewayUnavailable,
                        _mcp_client_module.MCPAgentNotEnrolled,
                    ) as exc:
                        log.warning("MCP unavailable — continuing without MCP tools: %s", exc)
                    except Exception:
                        log.exception("MCP tool loading failed — continuing without MCP tools")
                    _mcp_loaded = True

        # Build messages: system prompt + conversation history
        identity = state.get("identity_prompt", "You are a helpful assistant.")
        system_msg = SystemMessage(content=identity)

        # Get conversation messages (skip any existing system messages)
        conv_messages = [m for m in state["messages"] if not isinstance(m, SystemMessage)]

        agent_input = {"messages": [system_msg] + conv_messages}
        agent_id = state.get("agent_id", "default")
        config: dict[str, Any] = {
            "configurable": {"thread_id": f"{agent_id}/inner"},
        }

        # Attach Langfuse callback for tracing
        if langfuse_handler is not None:
            config["callbacks"] = [langfuse_handler]

        result = await inner_agent.ainvoke(agent_input, config=config)

        # Extract new messages from agent response
        new_messages = result.get("messages", [])
        # Only return messages the agent added (after our input)
        input_count = len(conv_messages) + 1  # +1 for system
        agent_new = new_messages[input_count:]

        return {"messages": agent_new}

    builder = StateGraph(CommandClawState)

    # Add nodes
    builder.add_node("load_identity", load_identity)
    builder.add_node("input_guardrails", input_guardrails)
    builder.add_node("agent", run_agent)
    builder.add_node("output_guardrails", output_guardrails)
    builder.add_node("block_and_notify", block_and_notify)

    # Wire edges
    builder.add_edge(START, "load_identity")
    builder.add_edge("load_identity", "input_guardrails")

    # Route after input guardrails: if violations, block; else proceed to agent
    builder.add_conditional_edges(
        "input_guardrails",
        route_guardrail_result,
        {"end": "agent", "block": "block_and_notify"},
    )

    builder.add_edge("agent", "output_guardrails")

    # Route after output guardrails
    builder.add_conditional_edges(
        "output_guardrails",
        route_guardrail_result,
        {"end": END, "block": "block_and_notify"},
    )

    builder.add_edge("block_and_notify", END)

    # Compile with checkpointer for conversation history
    checkpointer = MemorySaver()
    compiled = builder.compile(checkpointer=checkpointer)

    log.info("Agent graph built with %d tools, %d nodes", len(tools), len(builder.nodes))
    return TracedGraph(compiled)


class TracedGraph:
    """Wrapper that starts a Langfuse trace around every graph invocation.

    This ensures all graph nodes (guardrails, agent, block) appear as
    child observations within a single trace in Langfuse.
    """

    def __init__(self, graph: Any):
        self._graph = graph

    async def ainvoke(self, input_: dict[str, Any], config: dict | None = None, **kwargs: Any) -> Any:
        """Invoke the graph within a Langfuse trace context."""
        agent_id = input_.get("agent_id", "commandclaw")
        messages = input_.get("messages", [])
        user_input = ""
        if messages:
            last = messages[-1]
            user_input = last.content if hasattr(last, "content") else str(last)

        lf = None
        trace_ctx = None
        try:
            from langfuse import get_client as get_langfuse

            lf = get_langfuse()
            trace_ctx = lf.start_as_current_observation(
                name=agent_id,
                as_type="span",
                input={"message": user_input[:500]},
            )
            trace_ctx.__enter__()
        except Exception:
            lf = None
            trace_ctx = None

        try:
            result = await self._graph.ainvoke(input_, config=config, **kwargs)
        except Exception:
            if trace_ctx:
                try:
                    trace_ctx.__exit__(None, None, None)
                except Exception:
                    pass
            raise

        # Set trace-level I/O for the Langfuse dashboard
        ai_out = [m for m in result.get("messages", []) if isinstance(m, AIMessage) and m.content]
        output_text = ai_out[-1].content if ai_out else ""

        if lf is not None:
            try:
                lf.set_current_trace_io(
                    input={"message": user_input},
                    output={"response": output_text},
                )
                lf.update_current_span(output={"response": output_text})
            except Exception:
                log.debug("Failed to set Langfuse trace I/O", exc_info=True)

        if trace_ctx is not None:
            try:
                trace_ctx.__exit__(None, None, None)
            except Exception:
                pass

        return result
