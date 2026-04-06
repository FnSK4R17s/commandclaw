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
        # Telegram mode still uses old runtime for now
        from commandclaw.agent.runtime import create_agent

        agent_executor, cleanup_fn = asyncio.run(create_agent(settings))
        from commandclaw.telegram.bot import start_bot

        start_bot(agent_executor, settings, cleanup_fn)


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

    # --- Hatch flow: BOOTSTRAP.md exists → prompt user, then bootstrap ---
    bootstrap_path = settings.vault_path / "BOOTSTRAP.md"
    hatching = bootstrap_path.exists()

    if hatching:
        hatch_result = _collect_hatch_input(settings)
        if hatch_result is None:
            return  # user cancelled
        hatch_identity, hatch_intro = hatch_result
        _write_identity_file(settings.vault_path, hatch_identity)
    else:
        print(f"\nCommandClaw Chat — agent: {settings.agent_id} (type 'exit' to quit)\n")

    try:
        while True:
            # On first iteration during hatch, use collected input
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

            try:
                result = await graph.ainvoke(
                    {
                        "messages": [HumanMessage(content=message)],
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

            # After hatch completes, switch to normal chat
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
        flush_tracing()
        print("Goodbye.")


if __name__ == "__main__":
    main()
