"""CommandClaw entry point — CLI chat or Telegram bot."""

from __future__ import annotations

import asyncio
import logging
import sys

from commandclaw.config import Settings


def main() -> None:
    """Parse mode from argv, build agent, run."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("commandclaw")

    mode = sys.argv[1] if len(sys.argv) > 1 else "telegram"

    if mode not in ("chat", "telegram"):
        print("Usage: commandclaw [chat|telegram]")
        sys.exit(1)

    settings = Settings()

    if not settings.openai_api_key:
        log.error("COMMANDCLAW_OPENAI_API_KEY is required")
        sys.exit(1)

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

    agent_executor, cleanup_fn = asyncio.run(_bootstrap(settings))

    if mode == "chat":
        asyncio.run(_chat_loop(agent_executor, settings, cleanup_fn))
    else:
        from commandclaw.telegram.bot import start_bot
        start_bot(agent_executor, settings, cleanup_fn)


async def _bootstrap(settings: Settings) -> tuple:
    from commandclaw.agent.runtime import create_agent
    return await create_agent(settings)


async def _chat_loop(agent_executor, settings: Settings, cleanup_fn) -> None:
    """Interactive REPL — type messages, get agent responses."""
    from commandclaw.agent.retry import invoke_with_retry

    print("\nCommandClaw CLI Chat (type 'exit' or Ctrl+C to quit)\n")
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

            result = await invoke_with_retry(
                agent_executor,
                user_input,
                settings,
                session_id="cli",
                user_id="cli",
            )

            if result.success:
                print(f"\nagent> {result.output}\n")
            else:
                print(f"\n[error] {result.error}\n")
    except KeyboardInterrupt:
        print("\n")
    finally:
        await cleanup_fn()
        print("Goodbye.")


if __name__ == "__main__":
    main()
