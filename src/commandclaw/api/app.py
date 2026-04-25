"""FastAPI application with SSE streaming for CommandClaw agent."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from commandclaw.config import Settings

log = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str
    user_id: str | None = None


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    from commandclaw.agent.graph import build_agent_graph
    from commandclaw.agent.persistence import open_checkpointer
    from commandclaw.cli import resolve_settings

    settings = resolve_settings(Settings())
    os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)

    saver, close_checkpointer = await open_checkpointer(settings)
    agent, mcp_client = await build_agent_graph(settings, checkpointer=saver)

    application.state.settings = settings
    application.state.agent = agent
    application.state.mcp_client = mcp_client
    application.state.close_checkpointer = close_checkpointer

    log.info(
        "API server ready — agent=%s model=%s",
        settings.agent_id,
        settings.openai_model,
    )

    yield

    if mcp_client is not None:
        try:
            await mcp_client.disconnect()
        except Exception:
            log.exception("Error disconnecting MCP client")

    await close_checkpointer()

    from commandclaw.tracing.langfuse_tracing import flush_tracing

    flush_tracing()


app = FastAPI(title="CommandClaw", lifespan=lifespan)


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return {"status": "ok", "agent_id": settings.agent_id}


@app.post("/chat/{session_id}")
async def invoke_chat(session_id: str, body: ChatRequest, request: Request) -> JSONResponse:
    from commandclaw.agent.graph import invoke_agent

    settings: Settings = request.app.state.settings
    agent = request.app.state.agent

    result = await invoke_agent(
        agent,
        body.message,
        settings,
        session_id=session_id,
        user_id=body.user_id or session_id,
    )
    return JSONResponse({
        "output": result.output,
        "success": result.success,
        "error": result.error,
    })


@app.post("/chat/{session_id}/stream")
async def stream_chat(
    session_id: str, body: ChatRequest, request: Request,
) -> EventSourceResponse:
    from commandclaw.agent.graph import stream_agent

    settings: Settings = request.app.state.settings
    agent = request.app.state.agent

    async def event_generator() -> AsyncIterator[ServerSentEvent]:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        result_holder: list = []

        async def on_token(token: str) -> None:
            await queue.put(token)

        async def run_agent() -> None:
            try:
                result = await stream_agent(
                    agent,
                    body.message,
                    settings,
                    session_id=session_id,
                    user_id=body.user_id or session_id,
                    on_token=on_token,
                )
                result_holder.append(result)
            except Exception as exc:
                result_holder.append(exc)
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_agent())

        try:
            while True:
                token = await queue.get()
                if token is None:
                    break
                if await request.is_disconnected():
                    task.cancel()
                    return
                yield ServerSentEvent(data=token, event="token")

            if result_holder and isinstance(result_holder[0], Exception):
                exc = result_holder[0]
                yield ServerSentEvent(
                    data=json.dumps({"detail": str(exc)}),
                    event="error",
                )
            else:
                result = result_holder[0] if result_holder else None
                yield ServerSentEvent(
                    data=json.dumps({
                        "success": result.success if result else False,
                        "error": result.error if result else "No result",
                    }),
                    event="done",
                )
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    return EventSourceResponse(event_generator())
