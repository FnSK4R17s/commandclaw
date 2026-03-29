"""Connect to commandclaw-mcp gateway, discover available tools."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

log = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 30.0  # seconds


@dataclass
class MCPToolDef:
    """MCP tool definition as returned by the gateway."""

    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema


@dataclass
class MCPClient:
    """Lightweight async client for the commandclaw-mcp gateway.

    Usage::

        async with MCPClient(gateway_url=url, agent_key=key) as client:
            tools = await client.list_tools()
            result = await client.call_tool("my_tool", {"arg": "value"})
    """

    gateway_url: str
    agent_key: str

    # private — managed by connect/disconnect
    _session: ClientSession | None = field(default=None, repr=False, init=False)
    _transport_cm: Any = field(default=None, repr=False, init=False)
    _session_cm: Any = field(default=None, repr=False, init=False)

    # -- lifecycle ----------------------------------------------------------

    async def connect(self) -> None:
        """Initialize connection to the MCP gateway via streamable HTTP."""
        if self._session is not None:
            log.debug("MCPClient already connected — skipping")
            return

        headers = {"Authorization": f"Bearer {self.agent_key}"}
        log.info("Connecting to MCP gateway at %s", self.gateway_url)

        try:
            self._transport_cm = streamablehttp_client(
                url=self.gateway_url,
                headers=headers,
                timeout=_CONNECT_TIMEOUT,
            )
            read_stream, write_stream, _ = await self._transport_cm.__aenter__()

            self._session_cm = ClientSession(read_stream, write_stream)
            self._session = await self._session_cm.__aenter__()
            await self._session.initialize()
            log.info("MCP session initialized successfully")
        except Exception:
            log.exception("Failed to connect to MCP gateway")
            await self._cleanup()
            raise

    async def disconnect(self) -> None:
        """Close the session and transport cleanly."""
        log.info("Disconnecting from MCP gateway")
        await self._cleanup()

    async def _cleanup(self) -> None:
        """Best-effort teardown of session and transport context managers."""
        for cm_attr in ("_session_cm", "_transport_cm"):
            cm = getattr(self, cm_attr, None)
            if cm is not None:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:
                    log.debug("Ignoring error while closing %s", cm_attr)
            setattr(self, cm_attr, None)
        self._session = None

    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.disconnect()

    # -- operations ---------------------------------------------------------

    async def list_tools(self) -> list[MCPToolDef]:
        """Discover available tools from the gateway."""
        if self._session is None:
            raise RuntimeError("MCPClient is not connected — call connect() first")

        log.debug("Listing MCP tools")
        result = await self._session.list_tools()

        tools: list[MCPToolDef] = []
        for tool in result.tools:
            tools.append(
                MCPToolDef(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema,
                )
            )
        log.info("Discovered %d MCP tool(s): %s", len(tools), [t.name for t in tools])
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Call an MCP tool and return the text result.

        Returns the concatenated text content from the response.  If the tool
        reports an error, a ``RuntimeError`` is raised.
        """
        if self._session is None:
            raise RuntimeError("MCPClient is not connected — call connect() first")

        log.debug("Calling MCP tool %r with %s", name, arguments)
        result = await self._session.call_tool(name, arguments)

        if result.isError:
            msg = _extract_text(result.content)
            log.error("MCP tool %r returned error: %s", name, msg)
            raise RuntimeError(f"MCP tool {name!r} error: {msg}")

        text = _extract_text(result.content)
        log.debug("MCP tool %r returned %d chars", name, len(text))
        return text


def _extract_text(content: list[Any]) -> str:
    """Concatenate text content blocks from a CallToolResult."""
    parts: list[str] = []
    for block in content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts) if parts else ""
