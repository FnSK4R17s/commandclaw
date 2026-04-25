"""CLI entry point — parse mode, resolve settings, dispatch."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from commandclaw.config import Settings


def resolve_settings(settings: Settings) -> Settings:
    """Fill in vault_path and agent_id when not explicitly configured."""
    if settings.vault_path is None:
        from commandclaw.vault.workspace import create_workspace

        agent_id, vault_path = create_workspace(
            template_path=settings.vault_template,
            agent_id=settings.agent_id if settings.agent_id != "default" else None,
        )
        settings.vault_path = vault_path
        settings.agent_id = agent_id

    return settings


def parse_mode(argv: list[str] | None = None) -> str:
    """Extract the run mode from CLI arguments. Defaults to ``telegram``."""
    args = argv if argv is not None else sys.argv[1:]
    return args[0] if args else "telegram"


async def run_chat(settings: Settings) -> None:
    """Build the agent, wire a Dispatcher, and launch the Textual TUI."""
    from commandclaw.agent.graph import build_agent_graph, invoke_agent
    from commandclaw.agent.persistence import open_checkpointer
    from commandclaw.message.dispatcher import Dispatcher
    from commandclaw.tui.chat import ChatApp

    saver, close_checkpointer = await open_checkpointer(settings)
    agent, mcp_client = await build_agent_graph(settings, checkpointer=saver)

    app = ChatApp()

    def process_fn_factory(session_id: str):
        async def process_fn(envelope):
            result = await invoke_agent(
                agent, envelope.content, settings,
                session_id=session_id, user_id=session_id,
            )
            if result.success:
                app.display_agent_response(result.output)
            else:
                app._display_system(f"Error: {result.error or 'Unknown error'}")

        return process_fn

    dispatcher = Dispatcher(
        process_fn_factory,
        queue_maxsize=settings.queue_cap,
        discard_ttl=settings.discard_ttl_seconds,
    )
    app.dispatcher = dispatcher

    try:
        await app.run_async()
    finally:
        await dispatcher.shutdown()
        if mcp_client is not None:
            try:
                await mcp_client.disconnect()
            except Exception:
                pass
        await close_checkpointer()


def main() -> None:
    """Parse mode from argv, build graph, run."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("commandclaw")

    mode = parse_mode()

    if mode not in ("chat", "telegram", "bootstrap"):
        print("Usage: commandclaw [chat|telegram|bootstrap]")
        sys.exit(1)

    settings = Settings()

    if not settings.openai_api_key:
        log.error("COMMANDCLAW_OPENAI_API_KEY is required")
        sys.exit(1)

    os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)

    if mode == "telegram" and not settings.telegram_bot_token:
        log.error("COMMANDCLAW_TELEGRAM_BOT_TOKEN is required (or use 'commandclaw chat')")
        sys.exit(1)

    settings = resolve_settings(settings)

    log.info(
        "CommandClaw starting — mode=%s vault=%s model=%s",
        mode,
        settings.vault_path,
        settings.openai_model,
    )

    if mode in ("chat", "bootstrap"):
        logging.getLogger().handlers.clear()
        logging.getLogger().addHandler(logging.FileHandler(".commandclaw-chat.log"))
        asyncio.run(run_chat(settings))
    else:
        from commandclaw.telegram.bot import start_bot

        start_bot(settings)
