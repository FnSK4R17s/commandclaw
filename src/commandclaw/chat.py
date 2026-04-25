"""Interactive chat REPL and bootstrap loop.

.. deprecated::
    Replaced by ``commandclaw.tui.chat.ChatApp`` (Textual TUI).
    This module is retained for ``build_bootstrap_message`` and hatching logic
    only. The ``chat_loop`` function is no longer called from the CLI.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from commandclaw.config import Settings
from commandclaw.hatching import collect_hatch_input, write_identity_file

log = logging.getLogger(__name__)


def build_bootstrap_message(intro: str) -> str:
    """Construct the first-run bootstrap prompt sent to the agent."""
    return (
        "You are booting up for the first time. "
        "Read BOOTSTRAP.md and follow every step. "
        "IDENTITY.md has already been filled in by your human — do not overwrite it. "
        "Fill in USER.md, create today's daily note, "
        "and delete BOOTSTRAP.md when done.\n\n"
        "Here is what your human told you about themselves:\n"
        f"{intro or '(no introduction provided)'}"
    )


async def chat_loop(
    settings: Settings,
    agent: Any,
    mcp_client: Any,
    close_checkpointer: Callable[..., Any],
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[..., None] = print,
) -> None:
    """Interactive REPL. Handles both bootstrap (hatching) and normal chat.

    ``input_fn`` / ``print_fn`` are injectable for testing.
    """
    from commandclaw.agent.graph import invoke_agent
    from commandclaw.tracing.langfuse_tracing import flush_tracing

    bootstrap_path = settings.vault_path / "BOOTSTRAP.md"
    hatching = bootstrap_path.exists()

    hatch_intro: str | None = None
    if hatching:
        hatch_result = collect_hatch_input(
            settings.agent_id, input_fn=input_fn, print_fn=print_fn,
        )
        if hatch_result is None:
            await close_checkpointer()
            return
        hatch_identity, hatch_intro = hatch_result
        write_identity_file(settings.vault_path, hatch_identity)
    else:
        print_fn(f"\nCommandClaw Chat — agent: {settings.agent_id} (type 'exit' to quit)\n")

    try:
        while True:
            if hatching:
                message = build_bootstrap_message(hatch_intro or "")
            else:
                try:
                    user_input = input_fn("you> ")
                except EOFError:
                    break

                if user_input.strip().lower() in ("exit", "quit", "q"):
                    break
                if not user_input.strip():
                    continue
                # CLI slash commands — handled without agent invocation
                stripped = user_input.strip().lower()
                if stripped == "/stop":
                    print_fn("\n[stop] No active queue in CLI mode.\n")
                    continue
                if stripped == "/discarded":
                    print_fn("\n[discarded] No discarded messages.\n")
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
                print_fn(f"\nagent> {result.output}\n")
            else:
                log.error("Agent invocation failed: %s", result.error)
                print_fn(f"\n[error] {result.error}\n")

            if hatching:
                if not bootstrap_path.exists():
                    log.info("Bootstrap complete — BOOTSTRAP.md deleted by agent")
                    print_fn("CommandClaw Chat — (type 'exit' to quit)\n")
                else:
                    log.warning("Bootstrap ran but BOOTSTRAP.md still exists")
                hatching = False

    except KeyboardInterrupt:
        print_fn("\n")
    finally:
        if mcp_client is not None:
            try:
                await mcp_client.disconnect()
            except Exception:
                log.exception("Error disconnecting MCP client")
        await close_checkpointer()
        flush_tracing()
        print_fn("Goodbye.")
