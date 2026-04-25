"""Tests for commandclaw.tui.chat — Textual TUI chat app layout and behavior."""

from __future__ import annotations

from textual.widgets import Input, RichLog

from commandclaw.tui.chat import ChatApp


async def test_app_has_message_log_and_input() -> None:
    """ChatApp mounts a RichLog with id='message-log' and an Input with id='user-input'."""
    app = ChatApp()
    async with app.run_test() as pilot:
        assert app.query_one("#message-log", RichLog)
        assert app.query_one("#user-input", Input)


async def test_submit_text_appears_in_log() -> None:
    """Submitting text in the Input appends 'you> {text}' to the app's messages list."""
    app = ChatApp()
    async with app.run_test() as pilot:
        input_widget = app.query_one("#user-input", Input)
        input_widget.value = "hello world"
        await pilot.press("enter")
        assert "you> hello world" in app.messages


async def test_input_clears_after_submit() -> None:
    """After the user submits text, the Input value is reset to an empty string."""
    app = ChatApp()
    async with app.run_test() as pilot:
        input_widget = app.query_one("#user-input", Input)
        input_widget.value = "clear me"
        await pilot.press("enter")
        assert app.query_one("#user-input", Input).value == ""


async def test_submit_dispatches_envelope_to_dispatcher() -> None:
    """When ChatApp is given a dispatcher, submitting text dispatches a MsgEnvelope to it."""
    import asyncio
    from unittest.mock import AsyncMock

    from commandclaw.message.dispatcher import Dispatcher
    from commandclaw.message.envelope import MsgEnvelope

    mock_dispatcher = AsyncMock(spec=Dispatcher)

    app = ChatApp(dispatcher=mock_dispatcher)
    async with app.run_test() as pilot:
        input_widget = app.query_one("#user-input", Input)
        input_widget.value = "ask the agent"
        await pilot.press("enter")
        await asyncio.sleep(0)

    mock_dispatcher.dispatch.assert_called_once()
    called_envelope = mock_dispatcher.dispatch.call_args[0][0]
    assert isinstance(called_envelope, MsgEnvelope)
    assert called_envelope.session_id == "cli"
    assert called_envelope.content == "ask the agent"
    assert called_envelope.message_type == "user"


async def test_agent_response_appears_in_log() -> None:
    """A process_fn that calls app.display_agent_response causes 'agent> ...' to appear in messages."""
    import asyncio

    from commandclaw.message.dispatcher import Dispatcher

    app_ref: list[ChatApp] = []

    def factory(session_id: str):
        async def process_fn(envelope):
            app_ref[0].display_agent_response(f"echo: {envelope.content}")
        return process_fn

    dispatcher = Dispatcher(factory)
    app = ChatApp(dispatcher=dispatcher)
    app_ref.append(app)
    async with app.run_test() as pilot:
        input_widget = app.query_one("#user-input", Input)
        input_widget.value = "hello dispatcher"
        await pilot.press("enter")
        await asyncio.sleep(0.1)

    assert any(msg.startswith("agent> ") for msg in app.messages)


async def test_stop_command_aborts_dispatcher() -> None:
    """/stop calls dispatcher.abort('cli'), shows 'stopped' + count, does NOT dispatch a message."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from commandclaw.message.dispatcher import Dispatcher

    mock_dispatcher = MagicMock(spec=Dispatcher)
    mock_dispatcher.abort = AsyncMock(return_value=2)
    mock_dispatcher.dispatch = AsyncMock()

    app = ChatApp(dispatcher=mock_dispatcher)
    async with app.run_test() as pilot:
        input_widget = app.query_one("#user-input", Input)
        input_widget.value = "/stop"
        await pilot.press("enter")
        await asyncio.sleep(0)

    mock_dispatcher.abort.assert_called_once_with("cli")
    mock_dispatcher.dispatch.assert_not_called()
    stop_messages = [m for m in app.messages if "stopped" in m.lower() and "2" in m]
    assert stop_messages, f"Expected a 'stopped ... 2' message in {app.messages}"


async def test_discarded_command_lists_messages() -> None:
    """/discarded shows each discarded envelope with a 1-based index."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from commandclaw.message.dispatcher import Dispatcher
    from commandclaw.message.envelope import MsgEnvelope

    mock_dispatcher = MagicMock(spec=Dispatcher)
    mock_dispatcher.dispatch = AsyncMock()

    env1 = MsgEnvelope(session_id="cli", content="msg1", message_type="user")
    env2 = MsgEnvelope(session_id="cli", content="msg2", message_type="user")
    mock_dq = MagicMock()
    mock_dq.list_discarded.return_value = [env1, env2]
    mock_dispatcher.get_discard_queue.return_value = mock_dq

    app = ChatApp(dispatcher=mock_dispatcher)
    async with app.run_test() as pilot:
        input_widget = app.query_one("#user-input", Input)
        input_widget.value = "/discarded"
        await pilot.press("enter")
        await asyncio.sleep(0)

    mock_dispatcher.dispatch.assert_not_called()
    indexed = [m for m in app.messages if "1." in m and "msg1" in m]
    assert indexed, f"Expected a '1. msg1' message in {app.messages}"


async def test_recover_all_requeues_messages() -> None:
    """/recover all recovers all discarded envelopes and re-dispatches each one."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from commandclaw.message.dispatcher import Dispatcher
    from commandclaw.message.envelope import MsgEnvelope

    mock_dispatcher = MagicMock(spec=Dispatcher)
    mock_dispatcher.dispatch = AsyncMock()

    env1 = MsgEnvelope(session_id="cli", content="old1", message_type="user")
    env2 = MsgEnvelope(session_id="cli", content="old2", message_type="user")
    mock_dq = MagicMock()
    mock_dq.recover_all.return_value = [env1, env2]
    mock_dispatcher.get_discard_queue.return_value = mock_dq

    app = ChatApp(dispatcher=mock_dispatcher)
    async with app.run_test() as pilot:
        input_widget = app.query_one("#user-input", Input)
        input_widget.value = "/recover all"
        await pilot.press("enter")
        await asyncio.sleep(0)

    assert mock_dispatcher.dispatch.call_count == 2, (
        f"Expected dispatch called twice, got {mock_dispatcher.dispatch.call_count}"
    )


async def test_ctrl_c_aborts_dispatcher() -> None:
    """Pressing Ctrl+C calls dispatcher.abort('cli') and shows a 'stopped' message."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from commandclaw.message.dispatcher import Dispatcher

    mock_dispatcher = MagicMock(spec=Dispatcher)
    mock_dispatcher.abort = AsyncMock(return_value=1)

    app = ChatApp(dispatcher=mock_dispatcher)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+c")
        await asyncio.sleep(0)

    mock_dispatcher.abort.assert_called_once_with("cli")
    assert any("stopped" in m.lower() for m in app.messages)
