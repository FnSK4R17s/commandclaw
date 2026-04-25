"""Unit tests for the FastAPI API routes."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from commandclaw.agent.context import AgentResult


def _create_test_app() -> FastAPI:
    @asynccontextmanager
    async def fake_lifespan(application):
        application.state.settings = MagicMock()
        application.state.settings.agent_id = "test-agent"
        application.state.agent = MagicMock()
        application.state.mcp_client = None
        application.state.close_checkpointer = AsyncMock()
        yield

    test_app = FastAPI(lifespan=fake_lifespan)

    from commandclaw.api.app import health, invoke_chat, stream_chat

    test_app.add_api_route("/health", health, methods=["GET"])
    test_app.add_api_route("/chat/{session_id}", invoke_chat, methods=["POST"])
    test_app.add_api_route("/chat/{session_id}/stream", stream_chat, methods=["POST"])
    return test_app


@pytest.fixture
def client():
    with TestClient(_create_test_app()) as c:
        yield c


class TestHealthEndpoint:
    def test_health_returns_ok(self, client) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["agent_id"] == "test-agent"


class TestInvokeEndpoint:
    def test_invoke_returns_agent_result(self, client) -> None:
        result = AgentResult(output="hello", success=True)
        with patch(
            "commandclaw.agent.graph.invoke_agent",
            new=AsyncMock(return_value=result),
        ):
            resp = client.post("/chat/test-session", json={"message": "hi"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["output"] == "hello"
            assert data["success"] is True

    def test_invoke_returns_error(self, client) -> None:
        result = AgentResult(output="", success=False, error="boom")
        with patch(
            "commandclaw.agent.graph.invoke_agent",
            new=AsyncMock(return_value=result),
        ):
            resp = client.post("/chat/test-session", json={"message": "fail"})
            data = resp.json()
            assert data["success"] is False
            assert data["error"] == "boom"


class TestStreamEndpoint:
    def test_stream_returns_sse_events(self, client) -> None:
        result = AgentResult(output="hello world", success=True)

        async def fake_stream(agent, msg, settings, *, session_id, user_id, on_token=None):
            if on_token is not None:
                await on_token("hello ")
                await on_token("world")
            return result

        with patch(
            "commandclaw.agent.graph.stream_agent",
            side_effect=fake_stream,
        ):
            resp = client.post("/chat/test-session/stream", json={"message": "hi"})
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]

            text = resp.text.replace("\r\n", "\n")
            lines = text.strip().split("\n")
            events = [ln for ln in lines if ln.startswith("event:") or ln.startswith("data:")]
            token_events = [ln for ln in events if ln == "event: token"]
            done_events = [ln for ln in events if ln == "event: done"]
            assert len(token_events) == 2
            assert len(done_events) == 1
