# Integrating MCP with LangGraph: Solving the anyio/asyncio Conflict

**Author:** Background Research Agent (BEARY)
**Date:** 2026-03-31

---

## Abstract

The Model Context Protocol (MCP) Python SDK uses anyio for structured concurrency, while LangGraph runs on asyncio. These two async frameworks enforce fundamentally different resource management rules, producing `RuntimeError` and `CancelledError` exceptions that have been reported across at least nine downstream frameworks. This whitepaper analyzes the root cause -- anyio's LIFO cancel scope enforcement conflicting with asyncio's flexible task model -- and evaluates four integration strategies: raw httpx JSON-RPC calls bypassing the MCP SDK transport, background thread isolation (the Strands SDK pattern), anyio BlockingPortal bridging, and langchain-mcp-adapters ephemeral sessions. For CommandClaw, the recommended approach is raw httpx POST with JSON-RPC payloads targeting a stateless MCP gateway, which eliminates all anyio conflicts while preserving full protocol compatibility.

## The Problem: anyio vs asyncio in MCP + LangGraph

LangGraph is built on asyncio. The MCP Python SDK (v1.26.0) is built on anyio. On paper, anyio is designed to be a compatibility layer that runs on top of asyncio, so these should compose cleanly. In practice, they do not.

The `langchain-mcp-adapters` package (v0.2.2) [1] bridges between these two worlds by wrapping MCP tools as LangChain `StructuredTool` instances. At its orchestration level, the adapter uses `asyncio.create_task()` and `asyncio.gather()` directly [3]. Beneath it, the MCP SDK uses `anyio.create_task_group()`, `anyio.create_memory_object_stream()`, and anyio cancel scopes for all transport implementations -- stdio, SSE, and streamable HTTP alike [9][46].

This two-layer async architecture produces two well-documented failure modes.

**The cancel scope error.** When multiple MCP `ClientSession` instances are created and cleaned up, anyio requires strict LIFO (Last-In, First-Out) teardown ordering. Each session's `__aenter__()` creates a `TaskGroup` with a `CancelScope` bound to the current asyncio task [18]. If sessions are closed in any other order -- as commonly happens with `AsyncExitStack` -- anyio raises `RuntimeError: Attempted to exit cancel scope in a different task than it was entered in` [14][15][16][17]. This error has been reported in at least 8 separate MCP SDK issues and confirmed by community investigation as "a fundamental limitation of anyio's structured concurrency model" [17].

**The cancellation cascade.** When asyncio-native timeout mechanisms like `asyncio.wait_for()` fire during an MCP call, asyncio's cancellation conflicts with anyio's cancel scope system. The MCP module "wraps or replaces connection errors with CancelledError from a cancel scope deep within its internal async handling" [24], producing spurious exceptions that prevent proper error handling. This has been documented in LiteLLM [22], Google ADK [24][25], Pydantic AI [27], and OpenAgents [23].

The problem is ecosystem-wide. It affects Google ADK, PrefectHQ/fastmcp, LiteLLM, Pydantic AI, OpenAgents, lastmile-ai/mcp-agent, and langchain-mcp-adapters itself [22][23][24][25][26][27][28][29]. As of March 2026, the root cause remains unfixed in the MCP Python SDK, with issues #577 and #915 open at P1 priority [17][33].

## Root Cause Analysis

### anyio Task Groups and Cancel Scopes

anyio's structured concurrency model binds each `TaskGroup` to a `CancelScope`, and each `CancelScope` to the asyncio task that created it [13]. This binding is strict: scopes form a stack within each task, and they must be unwound in LIFO order. The anyio maintainer considers this intentional, not a bug (see agronholm/anyio#345) [17].

The MCP SDK's `BaseSession` creates a `TaskGroup` during `__aenter__()` to spawn a `receive_loop` background task [18]. When you create sessions A then B, the cancel scope stack for that asyncio task is `[scope_A, scope_B]`. Closing B first and then A works. Closing A first produces a scope mismatch because scope_B is still the "current" scope, and anyio refuses to exit scope_A from underneath it.

### LIFO Cleanup Ordering

`AsyncExitStack`, which `langchain-mcp-adapters` and many other frameworks use for managing multiple MCP sessions [8], guarantees LIFO cleanup by default. However, when exceptions occur during cleanup, partial unwinding can violate the ordering. When `asyncio.gather()` launches multiple cleanup coroutines concurrently, the ordering is nondeterministic. Both scenarios trigger the cancel scope error.

PR #787 partially addressed this by reversing cleanup order in `ClientSessionGroup` [30], but the fundamental issue persists because any user code that manages MCP sessions outside of strict nested `async with` blocks can violate the constraint.

### The Server-Side Variant

A related but distinct error -- `RuntimeError: Task group is not initialized. Make sure to use run()` -- occurs when mounting FastMCP's `streamable_http_app()` into Starlette or FastAPI applications [19][20]. Starlette's `Mount()` does not propagate sub-app lifespans, so the session manager's anyio task group never starts. The fix is explicit lifecycle management: `async with mcp.session_manager.run(): yield` in the parent app's lifespan handler [19].

## Solution 1: Raw httpx JSON-RPC (Recommended for CommandClaw)

The most direct solution is to bypass the MCP SDK's transport layer entirely. MCP uses standard JSON-RPC 2.0 over HTTP POST [48], and when the server is configured with `stateless_http=True` and `json_response=True`, each request is independent -- no session state, no SSE streaming, no `Mcp-Session-Id` header required [46].

This works because the anyio conflict is not caused by `anyio` being imported. It is caused by the SDK's transport code creating `anyio.create_task_group()` contexts that compete with asyncio's task scheduling [46]. `httpx.AsyncClient` uses anyio internally but in a self-contained way that does not create competing task groups in user space.

### Implementation

```python
import httpx
from typing import Any

MCP_GATEWAY_URL = "http://mcp-gateway:8080/mcp"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

class MCPRawClient:
    """Stateless MCP client using raw httpx JSON-RPC.
    
    Bypasses the MCP SDK transport layer entirely,
    avoiding all anyio task group conflicts.
    """

    def __init__(self, base_url: str = MCP_GATEWAY_URL):
        self.base_url = base_url
        self._request_id = 0
        self._client = httpx.AsyncClient(timeout=30.0)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def initialize(self) -> dict:
        """Send MCP initialize handshake.
        
        May be skippable with stateless servers, but included
        for protocol compliance and capability discovery.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "clientInfo": {
                    "name": "commandclaw",
                    "version": "1.0.0",
                },
            },
        }
        resp = await self._client.post(
            self.base_url, json=payload, headers=HEADERS
        )
        resp.raise_for_status()
        return resp.json()

    async def list_tools(self) -> list[dict]:
        """Retrieve available tools from the MCP server."""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        }
        resp = await self._client.post(
            self.base_url, json=payload, headers=HEADERS
        )
        resp.raise_for_status()
        result = resp.json()
        return result.get("result", {}).get("tools", [])

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> dict:
        """Call an MCP tool and return the result."""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        resp = await self._client.post(
            self.base_url, json=payload, headers=HEADERS
        )
        resp.raise_for_status()
        return resp.json().get("result", {})

    async def close(self):
        await self._client.aclose()
```

### LangGraph Integration

To use raw MCP tools in a LangGraph agent, convert them to LangChain `StructuredTool` instances:

```python
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent

async def build_agent(model, mcp_client: MCPRawClient):
    mcp_tools = await mcp_client.list_tools()
    
    langchain_tools = []
    for tool_def in mcp_tools:
        async def _call(arguments, _name=tool_def["name"]):
            result = await mcp_client.call_tool(_name, arguments)
            content = result.get("content", [])
            return "\n".join(
                block.get("text", "") 
                for block in content 
                if block.get("type") == "text"
            )

        langchain_tools.append(StructuredTool.from_function(
            func=None,
            coroutine=_call,
            name=tool_def["name"],
            description=tool_def.get("description", ""),
        ))

    return create_react_agent(model=model, tools=langchain_tools)
```

### Trade-offs

- **Pros:** Zero anyio exposure in user code. No session management complexity. No cancel scope issues. Works with any asyncio framework. Minimal dependencies (only httpx).
- **Cons:** Requires the MCP server to support `stateless_http=True` and `json_response=True`. Loses streaming SSE responses (all responses are buffered JSON). Cannot use MCP features that require session state (sampling, roots, elicitation). Each request is independent, so there is per-request overhead from the lack of connection reuse at the protocol level (though httpx reuses TCP connections).

## Solution 2: Background Thread with Dedicated Event Loop (Strands SDK Pattern)

The Strands Agents SDK [37] demonstrates a production-tested pattern: run the entire MCP SDK in a background thread with its own asyncio event loop. The main application communicates via `asyncio.run_coroutine_threadsafe()`.

### Implementation

```python
import asyncio
import threading
from contextlib import asynccontextmanager
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

class MCPThreadBridge:
    """Runs MCP SDK in a dedicated background thread to isolate
    anyio task groups from the main asyncio event loop."""

    def __init__(self, server_url: str):
        self._server_url = server_url
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: ClientSession | None = None
        self._ready = threading.Event()

    def start(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True
        )
        self._thread.start()
        # Block until MCP session is established
        future = asyncio.run_coroutine_threadsafe(
            self._init_session(), self._loop
        )
        future.result(timeout=30)
        self._ready.set()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _init_session(self):
        # All anyio code runs here, in the background loop
        self._transport_ctx = streamablehttp_client(
            self._server_url
        )
        streams = await self._transport_ctx.__aenter__()
        read_stream, write_stream, _ = streams
        self._session_ctx = ClientSession(
            read_stream, write_stream
        )
        self._session = await self._session_ctx.__aenter__()
        await self._session.initialize()

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Call from the main asyncio loop. Bridges to the
        background loop where the MCP session lives."""
        if not self._ready.is_set():
            raise RuntimeError("MCPThreadBridge not started")
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(name, arguments),
            self._loop,
        )
        return await asyncio.wrap_future(future)

    async def shutdown(self):
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self._cleanup(), self._loop
            )
            future.result(timeout=10)
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)

    async def _cleanup(self):
        if self._session:
            await self._session_ctx.__aexit__(None, None, None)
        if hasattr(self, '_transport_ctx'):
            await self._transport_ctx.__aexit__(None, None, None)
```

### Trade-offs

- **Pros:** Full MCP SDK compatibility including streaming, sessions, and all transport features. No server-side configuration requirements.
- **Cons:** Thread boundary adds latency (typically negligible, but measurable under load). Context variables do not propagate automatically across threads [39]. If the background loop crashes (e.g., server 5xx), subsequent `run_coroutine_threadsafe` calls hang indefinitely without health checks [38]. Shutdown sequencing is error-prone -- must signal the background loop to clean up MCP resources before stopping the loop.

## Solution 3: anyio BlockingPortal Bridge

anyio provides a first-class thread bridge via `BlockingPortal` [36]. This is conceptually similar to Solution 2 but uses anyio's managed lifecycle instead of raw threading.

### Implementation

```python
from anyio.from_thread import start_blocking_portal
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

class MCPPortalBridge:
    """Uses anyio BlockingPortal to run MCP SDK in an
    isolated event loop with managed lifecycle."""

    def __init__(self, server_url: str):
        self._server_url = server_url
        self._portal = None
        self._session = None

    def start(self):
        self._portal_ctx = start_blocking_portal(
            backend="asyncio"
        )
        self._portal = self._portal_ctx.__enter__()
        self._session = self._portal.call(self._init_session)

    async def _init_session(self):
        # Runs inside the portal's dedicated event loop
        transport_ctx = streamablehttp_client(self._server_url)
        streams = await transport_ctx.__aenter__()
        read_stream, write_stream, _ = streams
        session_ctx = ClientSession(read_stream, write_stream)
        session = await session_ctx.__aenter__()
        await session.initialize()
        return session

    def call_tool_sync(self, name: str, arguments: dict) -> dict:
        """Synchronous call -- blocks until result is ready."""
        return self._portal.call(
            self._session.call_tool, name, arguments
        )

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Async call from main loop -- offloads to portal thread."""
        return await asyncio.to_thread(
            self._portal.call,
            self._session.call_tool, name, arguments,
        )

    def shutdown(self):
        if self._portal_ctx:
            self._portal_ctx.__exit__(None, None, None)
```

For applications that need a lazy singleton portal, anyio 4.4+ provides `BlockingPortalProvider` [40], which starts the portal on first use and shuts it down when the last consumer exits.

### Trade-offs

- **Pros:** Cleaner lifecycle management than raw threading. anyio handles event loop creation and teardown. Full MCP SDK compatibility.
- **Cons:** `portal.call()` is a blocking call, so the async-to-async bridge (`call_tool` above) consumes a thread pool slot via `asyncio.to_thread`. Primarily designed for sync-to-async bridging, not async-to-async. The `BlockingPortal` does not support `await`-native access from external async code -- you must go through `asyncio.to_thread` or `run_coroutine_threadsafe`.

## Solution 4: langchain-mcp-adapters Ephemeral Sessions

The official `langchain-mcp-adapters` library [1] provides the simplest integration path. In its default ephemeral mode, `MultiServerMCPClient` creates a fresh `ClientSession` per tool invocation, executes the call, and tears down immediately [7].

### Implementation

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.prebuilt import create_react_agent

client = MultiServerMCPClient({
    "gateway": {
        "transport": "streamable_http",
        "url": "http://mcp-gateway:8080/mcp",
    }
})

# Ephemeral mode: each tool call creates/destroys a session
tools = await load_mcp_tools(connection=client.connections["gateway"])
agent = create_react_agent(model=model, tools=tools)
result = await agent.ainvoke({"messages": [("user", "query")]})
```

### Trade-offs

- **Pros:** Minimal code. Official library with LangChain ecosystem support. Handles tool conversion, pagination, interceptors, and callbacks automatically [4][6].
- **Cons:** Still uses anyio internally -- LIFO cleanup issues can surface under concurrent tool calls or when combined with `asyncio.wait_for()` [17][22]. Per-call session overhead (initialize + tool call + teardown) adds latency. Not suitable for MCP servers that require session state. The `streamable_http` transport specifically has documented 503 errors [29].

## Comparison of Approaches

| Criterion | Raw httpx (S1) | Background Thread (S2) | BlockingPortal (S3) | Ephemeral Sessions (S4) |
|---|---|---|---|---|
| anyio exposure | None | Isolated in thread | Isolated in thread | Full (hidden) |
| Cancel scope risk | None | None | None | Present |
| Session state support | No | Yes | Yes | No (ephemeral) |
| SSE streaming support | No | Yes | Yes | Yes |
| Per-call latency | Low (1 HTTP round-trip) | Low + thread bridge | Low + thread bridge | High (3 round-trips) |
| Code complexity | Low | High | Medium | Low |
| Server requirements | stateless_http + json_response | None | None | None |
| Context var propagation | N/A | Manual [39] | Manual | Automatic |
| Failure recovery | Standard HTTP retry | Health checks needed [38] | Portal restart | Automatic (new session) |
| Dependencies | httpx only | mcp SDK + threading | mcp SDK + anyio | langchain-mcp-adapters |

## CommandClaw Implementation Recommendation

For CommandClaw, the recommended approach is **Solution 1: raw httpx POST with JSON-RPC** targeting the MCP gateway.

The rationale is specific to CommandClaw's architecture:

1. **The gateway already supports stateless mode.** CommandClaw's MCP gateway is configured with `stateless_http=True`, meaning each request is processed independently with no session tracking [46]. This is the primary prerequisite for Solution 1, and it is already satisfied.

2. **No session state is needed.** CommandClaw's MCP tools (file operations, code execution, search) are stateless by design. There is no use of MCP sampling, roots, or elicitation features that would require persistent sessions.

3. **LangGraph + NeMo Guardrails double the asyncio conflict surface.** CommandClaw runs LangGraph graphs within NeMo Guardrails' action server, which itself calls `asyncio.run()` in some code paths. Adding the MCP SDK's anyio task groups to this stack creates a three-way async conflict. Raw httpx eliminates the MCP layer entirely from the conflict.

4. **Operational simplicity.** Solution 1 has no background threads to monitor, no context variable propagation to manage, and no shutdown sequencing to coordinate. A crashed httpx request is retried like any HTTP call. There is no hidden state that can drift out of sync.

5. **Forward-compatible with the MCP roadmap.** The MCP Transport Working Group's December 2025 roadmap [54] targets a fully stateless protocol by June 2026 -- eliminating the `initialize` handshake entirely and adding a discovery endpoint. Solution 1 aligns directly with this direction. When the new spec lands, the `initialize()` call can simply be removed.

The implementation path is:

1. Create an `MCPRawClient` class (as shown in Solution 1) in `commandclaw/tools/mcp_client.py`.
2. Register it as a LangGraph tool provider that converts MCP tool definitions to `StructuredTool` instances at graph build time.
3. Add `json_response=True` to the gateway's FastMCP configuration if not already set.
4. Add standard httpx retry/timeout configuration (exponential backoff, 30-second timeout, 3 retries).

If CommandClaw later needs session-stateful MCP features (sampling, elicitation), Solution 2 (background thread) would be the fallback. But given the current architecture and the protocol's trajectory toward statelessness, that scenario is unlikely.

## Conclusion

The anyio/asyncio conflict in MCP + LangGraph is a real, well-documented problem that affects the entire Python MCP ecosystem. It stems from a fundamental design tension: anyio's strict structured concurrency rules are incompatible with how asyncio frameworks manage concurrent resources. The MCP SDK team has not indicated plans to remove the anyio dependency, and anyio's maintainer considers the strict behavior intentional [17].

Four solutions exist on a spectrum from "avoid the problem entirely" (raw httpx) to "work within it carefully" (ephemeral sessions). The right choice depends on whether your MCP server requires session state and whether you control the server configuration.

For stateless MCP servers -- which is the direction the protocol itself is heading [54] -- raw httpx JSON-RPC is the simplest and most robust approach. It trades MCP SDK features you do not need (streaming, session state) for complete freedom from async framework conflicts you do not want.

## References

See [mcp-langgraph-integration-references.md](mcp-langgraph-integration-references.md) for the full bibliography.
In-text citations use bracketed IDs, e.g., [1], [2].
