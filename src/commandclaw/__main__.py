"""CommandClaw entry point — CLI chat, bootstrap, or Telegram bot."""

from __future__ import annotations

import asyncio
import logging
import os
import readline  # noqa: F401 — enables line editing (backspace, arrows) in input()
import sys
from pathlib import Path

from pydantic import BaseModel, field_validator

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

    if mode in ("chat", "bootstrap"):
        asyncio.run(_chat_loop(settings))
    else:
        from commandclaw.telegram.bot import start_bot

        start_bot(settings)


class HatchIdentity(BaseModel):
    """Agent identity fields collected during hatching."""

    name: str
    emoji: str = ""
    creature: str = ""
    vibe: str = ""

    @field_validator("name")
    @classmethod
    def name_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name is required")
        return v.strip()


def _collect_hatch_input(settings: Settings) -> tuple[HatchIdentity, str] | None:
    """Interactive prompts to collect identity + user intro. Returns None if cancelled."""
    print(f"\n🥚 Hatching agent: {settings.agent_id}\n")
    try:
        name = input("  Name your agent: ").strip()
        while not name:
            name = input("  Name is required: ").strip()
        emoji = input("  Signature emoji (optional): ").strip()
        creature = input("  Creature type — AI / robot / familiar / ghost / etc (optional): ").strip()
        vibe = input("  Vibe — personality in a word or two (optional): ").strip()

        identity = HatchIdentity(name=name, emoji=emoji, creature=creature, vibe=vibe)

        print("\nTell your agent about yourself — who you are, what you do,")
        print("what you want this agent to help with.\n")
        intro = input("hatch> ").strip()

        return identity, intro
    except (EOFError, KeyboardInterrupt):
        print("\nHatch cancelled.")
        return None


def _write_identity_file(vault_path: Path, identity: HatchIdentity) -> None:
    """Write the user-provided identity fields into IDENTITY.md."""
    content = (
        "# IDENTITY.md - Who Am I?\n"
        "\n"
        f"- **Name:** {identity.name}\n"
        f"- **Creature:** {identity.creature or '(choose your own)'}\n"
        f"- **Vibe:** {identity.vibe or '(choose your own)'}\n"
        f"- **Emoji:** {identity.emoji or '(choose your own)'}\n"
        "- **Avatar:** (path or URL)\n"
        "\n"
        "## Origin\n"
        "\n"
        "_(Write your origin story here. Who are you? What shaped you?"
        " This is your identity — make it yours.)_\n"
    )
    (vault_path / "IDENTITY.md").write_text(content)


async def _chat_loop(settings: Settings) -> None:
    """Interactive REPL using the new agent graph."""
    from commandclaw.agent.graph import build_agent_graph, invoke_agent
    from commandclaw.agent.persistence import open_checkpointer
    from commandclaw.tracing.langfuse_tracing import flush_tracing

    log = logging.getLogger("commandclaw")

    saver, close_checkpointer = await open_checkpointer(settings)
    agent, mcp_client = await build_agent_graph(settings, checkpointer=saver)

    bootstrap_path = settings.vault_path / "BOOTSTRAP.md"
    hatching = bootstrap_path.exists()

    if hatching:
        hatch_result = _collect_hatch_input(settings)
        if hatch_result is None:
            await close_checkpointer()
            return
        hatch_identity, hatch_intro = hatch_result
        _write_identity_file(settings.vault_path, hatch_identity)
    else:
        print(f"\nCommandClaw Chat — agent: {settings.agent_id} (type 'exit' to quit)\n")

    try:
        while True:
            if hatching:
                message = (
                    "You are booting up for the first time. "
                    "Read BOOTSTRAP.md and follow every step. "
                    "IDENTITY.md has already been filled in by your human — do not overwrite it. "
                    "Fill in USER.md, create today's daily note, "
                    "and delete BOOTSTRAP.md when done.\n\n"
                    "Here is what your human told you about themselves:\n"
                    f"{hatch_intro or '(no introduction provided)'}"
                )
            else:
                try:
                    user_input = input("you> ")
                except EOFError:
                    break

                if user_input.strip().lower() in ("exit", "quit", "q"):
                    break
                if not user_input.strip():
                    continue
                message = user_input

            result = await invoke_agent(
                agent,
                message,
                settings,
                session_id="cli",
                user_id="cli",
            )
            if result.success:
                print(f"\nagent> {result.output}\n")
            else:
                log.error("Agent invocation failed: %s", result.error)
                print(f"\n[error] {result.error}\n")

            if hatching:
                if not bootstrap_path.exists():
                    log.info("Bootstrap complete — BOOTSTRAP.md deleted by agent")
                    print("CommandClaw Chat — (type 'exit' to quit)\n")
                else:
                    log.warning("Bootstrap ran but BOOTSTRAP.md still exists")
                hatching = False

    except KeyboardInterrupt:
        print("\n")
    finally:
        if mcp_client is not None:
            try:
                await mcp_client.disconnect()
            except Exception:
                log.exception("Error disconnecting MCP client")
        await close_checkpointer()
        flush_tracing()
        print("Goodbye.")


if __name__ == "__main__":
    main()
