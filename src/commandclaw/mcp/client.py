"""Raw httpx-based MCP client — no anyio, no MCP SDK transport.

Speaks JSON-RPC 2.0 directly to the commandclaw-mcp gateway via HTTP POST.
Avoids the anyio/asyncio conflict that the MCP SDK's streamablehttp_client
causes when used alongside LangGraph's asyncio event loop.

Auth: bootstraps a phantom session via POST /sessions, then sends
Authorization: Bearer <phantom_token> on all /mcp requests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 30.0


class MCPGatewayUnavailableError(ConnectionError):
    """MCP gateway is not reachable."""


class MCPAgentNotEnrolledError(PermissionError):
    """Agent is not enrolled in the MCP gateway."""

# JSON-RPC headers for MCP protocol
_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


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
    """Async MCP client using raw httpx — no anyio, no MCP SDK transport.

    Usage::

        async with MCPClient(gateway_url=url, agent_id=agent_id) as client:
            tools = await client.list_tools()
            result = await client.call_tool("my_tool", {"arg": "value"})
    """

    gateway_url: str
    agent_id: str = ""
    agent_key: str = ""  # Simple bearer token (for non-gateway servers)

    # Private state
    _http: httpx.AsyncClient | None = field(default=None, repr=False, init=False)
    _gateway_session: GatewaySession | None = field(default=None, repr=False, init=False)
    _request_id: int = field(default=0, repr=False, init=False)
    _mcp_session_id: str | None = field(default=None, repr=False, init=False)
    _initialized: bool = field(default=False, repr=False, init=False)

    # -- helpers ------------------------------------------------------------

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _auth_headers(self) -> dict[str, str]:
        """Bearer token header from phantom session or agent_key."""
        if self._gateway_session:
            return {"Authorization": f"Bearer {self._gateway_session.phantom_token}"}
        if self.agent_key:
            return {"Authorization": f"Bearer {self.agent_key}"}
        return {}

    def _request_headers(self) -> dict[str, str]:
        """Full headers for a JSON-RPC POST to /mcp."""
        headers = {**_MCP_HEADERS, **self._auth_headers()}
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id
        return headers

    async def _jsonrpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send a JSON-RPC 2.0 request and return the result.

        Raises RuntimeError on JSON-RPC errors or HTTP errors.
        """
        if self._http is None:
            raise RuntimeError("MCPClient not connected — call connect() first")

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        resp = await self._http.post(
            self.gateway_url,
            json=payload,
            headers=self._request_headers(),
        )
        resp.raise_for_status()

        # Capture Mcp-Session-Id from response if present
        session_id = resp.headers.get("mcp-session-id")
        if session_id:
            self._mcp_session_id = session_id

        # Parse response — gateway may return JSON or SSE (text/event-stream)
        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            data = _parse_sse_response(resp.text)
        else:
            data = resp.json()

        # Check for JSON-RPC error
        if "error" in data:
            err = data["error"]
            code = err.get("code", -1)
            msg = err.get("message", "Unknown error")
            raise RuntimeError(f"MCP JSON-RPC error ({code}): {msg}")

        return data.get("result")

    # -- lifecycle ----------------------------------------------------------

    async def connect(self) -> None:
        """Bootstrap phantom session and initialize the MCP protocol."""
        if self._initialized:
            return

        # Ensure trailing slash — Starlette mount redirects /mcp to /mcp/
        if not self.gateway_url.endswith("/"):
            self.gateway_url += "/"

        self._http = httpx.AsyncClient(timeout=_TIMEOUT)

        # Bootstrap phantom session (gateway mode)
        if self.agent_id and not self.agent_key:
            self._gateway_session = await self._bootstrap_session()

        # MCP protocol initialize handshake
        log.info("Initializing MCP protocol at %s", self.gateway_url)
        result = await self._jsonrpc("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "commandclaw", "version": "1.0.0"},
        })

        # Send initialized notification (no response expected)
        notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        await self._http.post(
            self.gateway_url,
            json=notif,
            headers=self._request_headers(),
        )

        self._initialized = True
        proto = result.get("protocolVersion", "?") if result else "?"
        server = (result.get("serverInfo", {}) or {}).get("name", "?") if result else "?"
        log.info("MCP initialized — server=%s protocol=%s", server, proto)

    async def _bootstrap_session(self) -> GatewaySession:
        """Create a phantom session via POST /sessions."""
        base = self.gateway_url.rstrip("/")
        if base.endswith("/mcp"):
            base = base[:-4]
        sessions_url = f"{base}/sessions"

        log.info("Bootstrapping gateway session for agent %s", self.agent_id)
        try:
            resp = await self._http.post(sessions_url, json={"agent_id": self.agent_id})
        except httpx.ConnectError as exc:
            raise MCPGatewayUnavailableError(
                f"Cannot reach MCP gateway at {sessions_url}: {exc}"
            ) from None

        if resp.status_code == 404:
            detail = resp.json().get("error", resp.text)
            raise MCPAgentNotEnrolledError(
                f"Agent '{self.agent_id}' not enrolled in MCP gateway: {detail}"
            )
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

    async def disconnect(self) -> None:
        """Close the HTTP client."""
        if self._http:
            await self._http.aclose()
            self._http = None
        self._initialized = False
        self._mcp_session_id = None
        log.info("MCP client disconnected")

    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.disconnect()

    # -- operations ---------------------------------------------------------

    @property
    def is_gateway_authenticated(self) -> bool:
        return self._gateway_session is not None

    async def list_tools(self) -> list[MCPToolDef]:
        """Discover available tools from the gateway."""
        result = await self._jsonrpc("tools/list", {})

        tools: list[MCPToolDef] = []
        for tool_data in (result or {}).get("tools", []):
            tools.append(
                MCPToolDef(
                    name=tool_data["name"],
                    description=tool_data.get("description", ""),
                    input_schema=tool_data.get("inputSchema", {}),
                )
            )
        log.info("Discovered %d MCP tool(s): %s", len(tools), [t.name for t in tools])
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Call an MCP tool and return the text result."""
        log.debug("Calling MCP tool %r with %s", name, arguments)
        result = await self._jsonrpc("tools/call", {
            "name": name,
            "arguments": arguments,
        })

        if not result:
            return ""

        if result.get("isError"):
            msg = _extract_text(result.get("content", []))
            log.error("MCP tool %r returned error: %s", name, msg)
            raise RuntimeError(f"MCP tool {name!r} error: {msg}")

        return _extract_text(result.get("content", []))


def _parse_sse_response(text: str) -> dict[str, Any]:
    """Parse a text/event-stream response to extract the JSON-RPC message.

    SSE format: 'event: message\\ndata: {json}\\n\\n'
    """
    import json

    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise RuntimeError(f"No data line found in SSE response: {text[:200]}")


def _extract_text(content: list[dict[str, Any]]) -> str:
    """Concatenate text content blocks from a JSON-RPC tool result."""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts) if parts else ""
