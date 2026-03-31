"""CommandClaw entry point — CLI chat, bootstrap, or Telegram bot."""

from __future__ import annotations

import asyncio
import logging
import os
import readline  # noqa: F401 — enables line editing (backspace, arrows) in input()
import sys

from commandclaw.config import Settings


def main() -> None:
    """Parse mode from argv, build graph, run."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("commandclaw")

    mode = sys.argv[1] if len(sys.argv) > 1 else "telegram"

    if mode not in ("chat", "telegram", "bootstrap"):
        print("Usage: commandclaw [chat|telegram|bootstrap]")
        sys.exit(1)

    settings = Settings()

    if not settings.openai_api_key:
        log.error("COMMANDCLAW_OPENAI_API_KEY is required")
        sys.exit(1)

    # NeMo Guardrails uses langchain's OpenAI which reads OPENAI_API_KEY
    os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)

    if mode == "telegram" and not settings.telegram_bot_token:
        log.error("COMMANDCLAW_TELEGRAM_BOT_TOKEN is required (or use 'commandclaw chat')")
        sys.exit(1)

    # Resolve vault path: explicit > workspace manager
    if settings.vault_path is None:
        from commandclaw.vault.workspace import create_workspace

        agent_id, vault_path = create_workspace(
            template_path=settings.vault_template,
            agent_id=settings.agent_id if settings.agent_id != "default" else None,
        )
        settings.vault_path = vault_path
        settings.agent_id = agent_id
        log.info("Agent: %s", agent_id)

    log.info("CommandClaw starting — mode=%s vault=%s model=%s", mode, settings.vault_path, settings.openai_model)

    # Auto-bootstrap on first run if BOOTSTRAP.md exists
    bootstrap_path = settings.vault_path / "BOOTSTRAP.md"
    if bootstrap_path.exists() and mode != "bootstrap":
        log.info("BOOTSTRAP.md detected — running bootstrap first")
        asyncio.run(_run_bootstrap(settings))

    if mode == "bootstrap":
        asyncio.run(_run_bootstrap(settings))
    elif mode == "chat":
        asyncio.run(_chat_loop(settings))
    else:
        # Telegram mode still uses old runtime for now
        from commandclaw.agent.runtime import create_agent

        agent_executor, cleanup_fn = asyncio.run(create_agent(settings))
        from commandclaw.telegram.bot import start_bot

        start_bot(agent_executor, settings, cleanup_fn)


async def _invoke_graph(settings: Settings, message: str, session_id: str = "cli") -> str:
    """Invoke the agent graph with a single message. Returns the agent's response."""
    from langchain_core.messages import AIMessage, HumanMessage

    from commandclaw.agent.graph import build_agent_graph

    graph = build_agent_graph(settings)

    thread_id = f"{settings.agent_id or 'default'}/{session_id}"
    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content=message)],
            "session_type": "general",
            "trigger_source": "user",
            "user_id": session_id,
            "agent_id": settings.agent_id or "default",
            "memory_loaded": False,
            "vault_context": [],
            "guardrail_violations": [],
            "identity_prompt": "",
            "_vault_path": str(settings.vault_path),
        },
        config={"configurable": {"thread_id": thread_id}},
    )

    # Extract last AI message
    ai_messages = [m for m in result.get("messages", []) if isinstance(m, AIMessage) and m.content]
    return ai_messages[-1].content if ai_messages else "(no response)"


async def _run_bootstrap(settings: Settings) -> None:
    """Run the bootstrap session — agent sets up identity, deletes BOOTSTRAP.md."""
    bootstrap_path = settings.vault_path / "BOOTSTRAP.md"
    if not bootstrap_path.exists():
        print("No BOOTSTRAP.md found — nothing to do.")
        return

    log = logging.getLogger("commandclaw")
    log.info("Starting bootstrap session for %s", settings.agent_id)

    prompt = (
        "You are booting up for the first time. "
        "Read BOOTSTRAP.md and follow every step. "
        "Pick a creative name and identity for yourself. "
        "Fill in IDENTITY.md, create today's daily note, "
        "and delete BOOTSTRAP.md when done. "
        "My name is Shikhar, I go by Shikh4r online."
    )

    response = await _invoke_graph(settings, prompt, session_id="bootstrap")
    print(f"\n{response}\n")

    if not bootstrap_path.exists():
        log.info("Bootstrap complete — BOOTSTRAP.md deleted by agent")
    else:
        log.warning("Bootstrap ran but BOOTSTRAP.md still exists")


async def _chat_loop(settings: Settings) -> None:
    """Interactive REPL using the new agent graph."""
    from langchain_core.messages import AIMessage, HumanMessage

    from commandclaw.agent.graph import build_agent_graph
    from commandclaw.tracing.langfuse_tracing import flush_tracing

    log = logging.getLogger("commandclaw")

    graph = build_agent_graph(settings)
    thread_id = f"{settings.agent_id or 'default'}/cli"

    # Set Langfuse trace name to agent_id for all invocations in this session
    try:
        from langfuse import propagate_attributes
        propagate_attributes(
            trace_name=settings.agent_id or "commandclaw",
            tags=["commandclaw"],
        )
    except Exception:
        pass

    print(f"\nCommandClaw Chat — agent: {settings.agent_id} (type 'exit' to quit)\n")

    try:
        while True:
            try:
                user_input = input("you> ")
            except EOFError:
                break

            if user_input.strip().lower() in ("exit", "quit", "q"):
                break
            if not user_input.strip():
                continue

            try:
                result = await graph.ainvoke(
                    {
                        "messages": [HumanMessage(content=user_input)],
                        "session_type": "general",
                        "trigger_source": "user",
                        "user_id": "cli",
                        "agent_id": settings.agent_id or "default",
                        "memory_loaded": False,
                        "vault_context": [],
                        "guardrail_violations": [],
                        "identity_prompt": "",
                        "_vault_path": str(settings.vault_path),
                    },
                    config={"configurable": {"thread_id": thread_id}},
                )

                ai_messages = [
                    m for m in result.get("messages", [])
                    if isinstance(m, AIMessage) and m.content
                ]
                output = ai_messages[-1].content if ai_messages else "(no response)"
                print(f"\nagent> {output}\n")

            except Exception as exc:
                log.exception("Agent invocation failed")
                print(f"\n[error] {exc}\n")

    except KeyboardInterrupt:
        print("\n")
    finally:
        flush_tracing()
        print("Goodbye.")


if __name__ == "__main__":
    main()
