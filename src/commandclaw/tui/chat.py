from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Input, RichLog

from commandclaw.message.envelope import MsgEnvelope


class ChatApp(App):
    TITLE = "CommandClaw Chat"
    BINDINGS = [
        Binding("ctrl+c", "abort", "Stop agent", priority=True),
    ]

    def __init__(self, dispatcher=None, **kwargs):
        super().__init__(**kwargs)
        self.messages: list[str] = []
        self.dispatcher = dispatcher

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="message-log")
        yield Input(placeholder="Type a message...", id="user-input")

    def on_mount(self) -> None:
        self.query_one("#user-input", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        msg = f"you> {text}"
        self.messages.append(msg)
        self.query_one("#message-log", RichLog).write(msg)
        event.input.value = ""

        if self.dispatcher is None:
            return

        if text == "/stop":
            count = await self.dispatcher.abort("cli")
            self._display_system(f"Agent stopped. {count} messages discarded.")
            return

        if text == "/discarded":
            try:
                dq = self.dispatcher.get_discard_queue("cli")
                items = dq.list_discarded()
            except KeyError:
                self._display_system("No session active.")
                return
            if not items:
                self._display_system("No discarded messages.")
                return
            for i, env in enumerate(items, start=1):
                self._display_system(f"{i}. {env.content}")
            return

        if text.startswith("/recover"):
            parts = text.split(maxsplit=1)
            arg = parts[1] if len(parts) > 1 else ""
            try:
                dq = self.dispatcher.get_discard_queue("cli")
            except KeyError:
                self._display_system("No session active.")
                return
            if arg.lower() == "all":
                recovered = dq.recover_all()
                for env in recovered:
                    await self.dispatcher.dispatch(env)
                self._display_system(f"Recovered {len(recovered)} messages.")
            else:
                try:
                    idx = int(arg) - 1
                    env = dq.recover(idx)
                    await self.dispatcher.dispatch(env)
                    self._display_system(f"Recovered: {env.content}")
                except (ValueError, IndexError):
                    self._display_system("Usage: /recover <n> or /recover all")
            return

        envelope = MsgEnvelope(session_id="cli", content=text, message_type="user")
        await self.dispatcher.dispatch(envelope)

    async def action_abort(self) -> None:
        if self.dispatcher is None:
            return
        count = await self.dispatcher.abort("cli")
        self._display_system(f"Agent stopped. {count} messages discarded.")

    def _display_system(self, text: str) -> None:
        msg = f"[system] {text}"
        self.messages.append(msg)
        try:
            self.query_one("#message-log", RichLog).write(msg)
        except Exception:
            pass

    def display_agent_response(self, text: str) -> None:
        msg = f"agent> {text}"
        self.messages.append(msg)
        try:
            self.query_one("#message-log", RichLog).write(msg)
        except Exception:
            pass  # app may not be mounted (e.g. called after exit)
