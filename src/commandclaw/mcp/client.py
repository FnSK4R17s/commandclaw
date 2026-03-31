"""Connect to commandclaw-mcp gateway, discover available tools.

Supports two auth modes:
1. Phantom token + HMAC (full gateway auth — production)
2. Simple Bearer token (for testing / third-party MCP servers)
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

log = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 30.0


@dataclass
class MCPToolDef:
    """MCP tool definition as returned by the gateway."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class GatewaySession:
    """Phantom session returned by POST /sessions."""

    phantom_token: str
    hmac_key: str
    expires_at: str
    agent_id: str


@dataclass
class MCPClient:
    """Async client for the commandclaw-mcp gateway.

    Usage::

        async with MCPClient(gateway_url=url, agent_id=agent_id) as client:
            tools = await client.list_tools()
            result = await client.call_tool("my_tool", {"arg": "value"})

    For simple Bearer auth (non-gateway MCP servers)::

        client = MCPClient(gateway_url=url, agent_key="bearer-token")
    """

    gateway_url: str
    agent_id: str = ""
    agent_key: str = ""  # Simple bearer token (fallback)

    # Private state
    _session: ClientSession | None = field(default=None, repr=False, init=False)
    _transport_cm: Any = field(default=None, repr=False, init=False)
    _session_cm: Any = field(default=None, repr=False, init=False)
    _gateway_session: GatewaySession | None = field(default=None, repr=False, init=False)

    # -- gateway auth -------------------------------------------------------

    async def _bootstrap_session(self) -> GatewaySession:
        """Create a phantom session via POST /sessions."""
        # Strip trailing /mcp path to get the gateway base URL
        base = self.gateway_url.rstrip("/")
        if base.endswith("/mcp"):
            base = base[:-4]
        sessions_url = f"{base}/sessions"

        log.info("Bootstrapping gateway session for agent %s at %s", self.agent_id, sessions_url)
        async with httpx.AsyncClient(timeout=_CONNECT_TIMEOUT) as http:
            resp = await http.post(sessions_url, json={"agent_id": self.agent_id})
            resp.raise_for_status()
            data = resp.json()

        session = GatewaySession(
            phantom_token=data["phantom_token"],
            hmac_key=data["hmac_key"],
            expires_at=data["expires_at"],
            agent_id=data["agent_id"],
        )
        log.info("Gateway session created, expires %s", session.expires_at)
        return session

    def _sign_headers(self, method: str, path: str, body: bytes = b"") -> dict[str, str]:
        """Build phantom token + HMAC auth headers for a request."""
        if self._gateway_session is None:
            raise RuntimeError("No gateway session — call connect() first")

        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        body_hash = hashlib.sha256(body).hexdigest()
        canonical = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body_hash}"
        signature = hmac_mod.new(
            self._gateway_session.hmac_key.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()

        return {
            "X-Phantom-Token": self._gateway_session.phantom_token,
            "X-Timestamp": timestamp,
            "X-Signature": signature,
            "X-Nonce": nonce,
        }

    def _build_headers(self) -> dict[str, str]:
        """Build request headers — phantom token as Bearer or simple key."""
        if self._gateway_session:
            # MCP streamable HTTP transport uses static headers, so we send
            # the phantom token as Bearer. The gateway accepts this as fallback.
            return {"Authorization": f"Bearer {self._gateway_session.phantom_token}"}
        elif self.agent_key:
            return {"Authorization": f"Bearer {self.agent_key}"}
        return {}

    # -- lifecycle ----------------------------------------------------------

    async def connect(self) -> None:
        """Initialize connection to the MCP gateway."""
        if self._session is not None:
            log.debug("MCPClient already connected — skipping")
            return

        # Bootstrap phantom session if we have an agent_id (gateway mode)
        if self.agent_id and not self.agent_key:
            self._gateway_session = await self._bootstrap_session()

        headers = self._build_headers()
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

    @property
    def is_gateway_authenticated(self) -> bool:
        """Whether we have an active phantom session with the gateway."""
        return self._gateway_session is not None

    async def list_tools(self) -> list[MCPToolDef]:
        """Discover available tools from the gateway."""
        if self._session is None:
            raise RuntimeError("MCPClient is not connected — call connect() first")

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
        """Call an MCP tool and return the text result."""
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
