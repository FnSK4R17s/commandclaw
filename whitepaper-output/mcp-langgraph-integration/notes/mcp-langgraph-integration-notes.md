# MCP-LangGraph Integration -- Research Notes

**Author:** Background Research Agent (BEARY)
**Date:** 2026-03-31

---

## General Understanding

### Q1: How does LangChain/LangGraph officially integrate with MCP servers, and what async patterns does it use?

**1. The `langchain-mcp-adapters` Package: Overview and Architecture**

The `langchain-mcp-adapters` package (current version 0.2.2, released 2026-03-16) is the official LangChain library for integrating MCP tools with LangChain and LangGraph agents [1]. It is authored by Vadym Barda at LangChain and licensed under MIT [2]. Its core dependencies are `langchain-core>=1.0.0,<2.0.0`, `mcp>=1.9.2`, and `typing-extensions>=4.14.0` [3].

The package implements a layered architecture with five tiers: Application Layer (user code), Client Layer (`MultiServerMCPClient`), Adapter Layer (format converters for tools/prompts/resources), Extension Layer (interceptors and callbacks), and Session/Transport Layer (connection management via the MCP SDK) [4].

**2. Tool Wrapping Mechanism: MCP to LangChain**

The core conversion happens in two functions [4][5]:

- `load_mcp_tools(session, *, connection, ...)` -- an async function that takes either an active `ClientSession` or a `Connection` config, retrieves all MCP tools (handling pagination via `nextCursor` with a safety limit of 1000 iterations), and converts each using `convert_mcp_tool_to_langchain_tool()`.

- `convert_mcp_tool_to_langchain_tool()` -- creates a LangChain `StructuredTool` instance with the following mapping:
  - `name` from MCP tool name (optionally prefixed with server name for collision avoidance)
  - `description` from MCP tool metadata
  - `args_schema` converted from MCP's JSON Schema `inputSchema` into a Pydantic model
  - `coroutine` set to an async `call_tool` wrapper function
  - `response_format` always set to `"content_and_artifact"`
  - `metadata` containing MCP annotations

The tool execution pipeline when invoked: (1) agent calls `tool.ainvoke(args)`, (2) request passes through interceptor chain (onion pattern), (3) base handler `execute_tool()` creates/uses an MCP session and calls `session.call_tool(name, args)`, (4) `_convert_call_tool_result()` transforms MCP content blocks (TextContent, ImageContent, EmbeddedResource, etc.) to LangChain format, returning a `(content, artifact)` tuple [4][5].

**3. MCP Client Session Lifecycle**

The session lifecycle operates in two modes [1][6][7]:

**Ephemeral sessions (default):** `MultiServerMCPClient` is stateless by default. Each tool invocation creates a fresh `ClientSession`, executes the tool, and cleans up. This is intentional for web deployment compatibility, as confirmed by maintainer eyurtsev: "The default behavior should not be a stateful connection. It produces issues for web deployments." [7]

**Persistent sessions:** For stateful MCP servers, explicit session management is available:
```python
async with client.session("server_name") as session:
    tools = await load_mcp_tools(session)
    # tools remain bound to this live session
```
The `session()` method uses `@asynccontextmanager` and the session remains open for the duration of the context block [1][6].

For LangGraph API server deployment with persistent sessions, users must return an async context manager from `make_graph`:
```python
@asynccontextmanager
async def make_graph():
    async with client.session("server") as session:
        tools = await load_mcp_tools(session)
        yield create_react_agent(model=model, tools=tools)
```
For multiple servers, `AsyncExitStack` is used to manage multiple concurrent sessions [8].

**4. Async Patterns: anyio vs asyncio**

The async story has two layers [3][9][10]:

**At the `langchain-mcp-adapters` level:** The package uses standard Python `asyncio` directly. The `client.py` module imports `asyncio` and uses `asyncio.create_task()` and `asyncio.gather()` for concurrent tool loading across multiple servers. The `tools.py` module does not import either `anyio` or `asyncio` -- it relies on native `async/await` syntax [3].

**At the underlying `mcp` SDK level:** The MCP Python SDK (>= 1.9.2) uses **anyio >= 4.5** as its async foundation rather than asyncio directly. This provides support for both asyncio and Trio backends, structured concurrency via task groups, and transport-agnostic memory streams (`MemoryObjectReceiveStream`/`MemoryObjectSendStream`). All transport implementations (stdio, SSE, streamable HTTP) use anyio memory streams internally [9][10].

This creates a practical tension: `langchain-mcp-adapters` uses `asyncio.gather()` at the orchestration level, while the MCP SDK uses `anyio` primitives at the transport level. Since anyio runs on top of asyncio by default, this works in practice but can cause issues in certain environments [3][10].

**5. LangGraph Integration Patterns**

The standard LangGraph integration uses the `ToolNode` prebuilt component [1]:
```python
from langgraph.prebuilt import ToolNode, tools_condition

builder = StateGraph(MessagesState)
builder.add_node("call_model", call_model_fn)
builder.add_node("tools", ToolNode(tools))
builder.add_edge(START, "call_model")
builder.add_conditional_edges("call_model", tools_condition)
graph = builder.compile()
```

The library also supports LangGraph's `Command` type for control flow -- interceptors can return `Command` objects to redirect graph execution to specific nodes or terminate early [6].

**6. Advanced Features: Interceptors and Callbacks**

Interceptors follow an onion/middleware pattern, receiving `MCPToolCallRequest` objects and a `next_handler` callable. They can modify requests, short-circuit execution, transform results, or return LangGraph `Command` objects. Common patterns include logging, retry logic with exponential backoff, authentication header injection, and state-based access control [6].

**7. Known Issues and Workarounds**

- **Session statefulness (Issue #207):** The default ephemeral session behavior breaks stateful MCP servers. Workaround: use `client.session()` async context manager [7].
- **Blocking sync on Windows stdio (Issue #157):** The MCP client's Windows stdio implementation calls `shutil.which()` (blocking I/O) inside `stdio_client()`. Workarounds: use `asyncio.to_thread()`, or run with `langgraph dev --allow-blocking` [11].
- **Session persistence with LangGraph (Issue #189):** Wrapping session creation in `async with` and returning the agent causes `ClosedResourceError`. Solution: use `@asynccontextmanager` pattern to yield the graph from within the session scope [8].
- **Async generator warnings (Issue #254):** Tool loading can yield warnings about ignored async generators [12].

**8. Transport Options**

Four transports are supported [1][4]: `stdio` (subprocess), `http` (standard HTTP), `streamable_http` (streaming HTTP with SSE), and `sse` (Server-Sent Events, legacy).

---

### Q2: What is the anyio vs asyncio compatibility problem with MCP's streamable HTTP transport, and how have others solved it?

**1. The Core Problem: anyio's Structured Concurrency vs. asyncio's Flexible Task Model**

The MCP Python SDK is built on `anyio`, which enforces strict structured concurrency rules: cancel scopes must be entered and exited in the same task, and task groups must be torn down in LIFO order [13]. When MCP clients are used within asyncio-based frameworks like LangGraph, these constraints are frequently violated.

**2. Error #1: "Attempted to exit cancel scope in a different task than it was entered in"**

This is the most widely reported error, documented across at least 8 issues in the MCP SDK repo (issues #79, #252, #521, #577, #831, #915, #922) [14][15][16][17]. The root cause:

- The MCP SDK's `BaseSession` creates an anyio `TaskGroup` in its `__aenter__()` to run a `receive_loop` background task [18].
- Each `TaskGroup` creates a `CancelScope` that binds to the current asyncio task.
- When multiple `ClientSession` instances are created sequentially, each new cancel scope replaces the previous one as the "current" scope for that task.
- If sessions are cleaned up in any order other than strict LIFO, anyio detects a scope mismatch and raises the `RuntimeError` [18].

A deep investigation by user @cbcoutinho on issue #577 confirmed this is "a fundamental limitation of anyio's structured concurrency model" when combined with `AsyncExitStack`, and that the anyio maintainer considers this behavior intentional [17].

**3. Error #2: "Task group is not initialized. Make sure to use run()"**

This error affects the server side when mounting FastMCP's `streamable_http_app()` into existing ASGI applications. `FastMCP.streamable_http_app()` embeds its session manager startup inside the app's lifespan context, but Starlette's `Mount()` does not propagate sub-app lifespans [19][20]. The session manager's internal anyio task group never gets initialized.

This was partially addressed by PR #841 which fixed unhandled exceptions killing the session manager, but the mounting/lifespan issue persists [21].

**4. The asyncio.wait_for vs. anyio.fail_after Conflict**

When asyncio-native code wraps MCP calls with `asyncio.wait_for()`, the timeout firing conflicts with anyio's cancel scope system, producing spurious `CancelledError` exceptions that cascade through the TaskGroup [22][23]. The MCP module effectively "wraps or replaces connection errors with CancelledError from a cancel scope deep within its internal async handling" [24].

**5. Impact on Downstream Frameworks**

This problem is reported across the ecosystem:
- **Google ADK**: Issues #2196, #3708, #3788 document cancel scope errors during MCPToolset teardown [25][24].
- **PrefectHQ/fastmcp**: Issue #348 documents failures in pytest-asyncio tests during FastMCPClient teardown [26].
- **LiteLLM**: Issue #22928 documents MCP tool discovery failing with remote Streamable HTTP servers [22].
- **Pydantic AI**: Issue #2401 documents TimeoutError during MCPServerStreamableHTTP initialization [27].
- **OpenAgents**: Issue #300 documents CancelledError during streamable_http session initialization [23].
- **lastmile-ai/mcp-agent**: Issue #35 documents the cancel scope error [28].
- **langchain-mcp-adapters**: Issue #333 documents 503 errors with streamable_http [29].

**6. Workarounds**

- **Ensure LIFO cleanup order:** Clean up MCP clients in reverse order of creation. PR #787 fixed `ClientSessionGroup` by reversing cleanup order [30].
- **Use nested `async with` blocks instead of `AsyncExitStack`:** Nested context managers naturally enforce LIFO cleanup [17].
- **Run each client in its own async context:** Using `asyncio.gather()` with each client in a separate coroutine isolates their cancel scopes [17].
- **Explicitly run session manager in parent lifespan:** For "Task group not initialized" error, call `async with mcp.session_manager.run(): yield` in parent lifespan [19].
- **Remove `nest_asyncio`:** At least one user found removing `nest_asyncio.apply()` eliminated errors [31].
- **Use `anyio.fail_after()` instead of `asyncio.wait_for()`:** Avoids cross-framework cancellation conflicts [22].
- **Shield cleanup code with `CancelScope(shield=True)`:** Prevents premature cancellation during cleanup [32].

**7. Current Status (March 2026)**

The problem remains **unfixed at its root** in MCP Python SDK v1.26.0. Issues #577 and #915 remain open with P1 priority [17][33]. There is no indication the SDK team plans to replace anyio with pure asyncio, nor that anyio plans to relax its structured concurrency rules. PEP 789 (limiting yield in async generators) may eventually help but is not yet implemented [34].

---

### Q3: What patterns exist for running an anyio-based MCP connection in a separate thread alongside an asyncio application?

**1. Pattern A: Dedicated Background Thread with `asyncio.run_coroutine_threadsafe`**

The most battle-tested pattern is exemplified by the **Strands Agents SDK** (`strands-agents/sdk-python`). Their `MCPClient` class [37] uses:

- A background thread running its own asyncio event loop (`asyncio.new_event_loop()` + `loop.run_forever()`).
- The MCP `ClientSession` and all anyio-based transport code run entirely within this background thread's event loop.
- The main application thread communicates via `asyncio.run_coroutine_threadsafe(coro, self._background_thread_event_loop)`, returning a `concurrent.futures.Future`.
- The caller can `.result(timeout=...)` synchronously or `await asyncio.wrap_future(future)` from the main asyncio loop.

Key lessons from Strands [38][39]:
- If the background event loop exits prematurely (e.g., due to 4xx/5xx errors), subsequent `run_coroutine_threadsafe` calls hang indefinitely. Health-check mechanisms are needed.
- The background thread does not automatically inherit `contextvars` from the calling thread. Explicit context var propagation is required.
- Graceful shutdown: signal the background loop to stop via an async close event, then `thread.join()`.

Pseudocode:
```python
import asyncio
import threading

class MCPBridge:
    def __init__(self):
        self._loop = None
        self._thread = None

    def start(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        future = asyncio.run_coroutine_threadsafe(
            self._init_mcp_session(), self._loop
        )
        future.result(timeout=30)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def call_tool(self, name, args):
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(name, args), self._loop
        )
        return await asyncio.wrap_future(future)
```

**2. Pattern B: AnyIO `BlockingPortal` / `start_blocking_portal`**

AnyIO provides a first-class mechanism: `anyio.from_thread.start_blocking_portal()` [35][36]. It launches a new event loop in a dedicated thread and returns a `BlockingPortal` context manager. From any external thread, `portal.call(async_fn, *args)` executes async code on that loop and blocks until the result is ready. The portal also supports `portal.start_task_soon()` and `portal.wrap_async_context_manager()`.

**3. Pattern C: AnyIO `BlockingPortalProvider` (Lazy Singleton)**

Added in anyio 4.4 [40], `BlockingPortalProvider` implements a lazy singleton pattern: the first thread to enter starts the portal; the last thread to exit shuts it down.

**4. Pattern D: Async-to-Async Bridge Across Threads**

When the main application is itself async (like LangGraph):
1. Start the anyio/MCP event loop in a background thread (Pattern A or B).
2. From the main asyncio coroutine, use `asyncio.run_coroutine_threadsafe()` to schedule work on the background loop, then `await asyncio.wrap_future(future)` to await without blocking.

**5. AnyIO's Built-in Thread Bridge APIs**

AnyIO provides [36]:
- `anyio.to_thread.run_sync(sync_fn)`: Run blocking sync code in a worker thread from async context.
- `anyio.from_thread.run(async_fn)` / `anyio.from_thread.run_sync(sync_fn)`: Call back into the event loop from within a worker thread spawned by `to_thread.run_sync()`. Only works in anyio-spawned threads, not arbitrary external threads.
- For external threads, `BlockingPortal` is required [36].

**6. Thread-Safe Communication Patterns**

For robust cross-thread communication [35][37]:
- `concurrent.futures.Future`: Returned by `run_coroutine_threadsafe()`, awaitable via `asyncio.wrap_future()`.
- `janus` library: Provides a queue that works across sync/async boundaries.
- Threading primitives: Use `await asyncio.to_thread(queue.get)` rather than blocking directly.

---

### Q4: What alternative MCP transport options exist that avoid the anyio conflict?

**1. All MCP SDK transports depend on anyio**

Both the SSE client transport (`mcp.client.sse`) and the Streamable HTTP client transport (`mcp.client.streamable_http`) import and use `anyio` directly [46]. `mcp/client/sse.py` uses `anyio.create_memory_object_stream`, `anyio.create_task_group`, and `anyio.TASK_STATUS_IGNORED`. `mcp/client/streamable_http.py` uses the same primitives plus `anyio.sleep`. The SSE transport does **not** avoid anyio [46].

**2. Streamable HTTP supports SSE and JSON response modes**

The MCP spec (2025-03-26) states that for JSON-RPC POSTs, the server MUST respond with either `Content-Type: text/event-stream` or `Content-Type: application/json`, and the client MUST support both [48].

**3. FastMCP `json_response=True` and `stateless_http=True`**

In FastMCP server configuration [46]:
- `json_response=True`: Server returns `application/json` responses instead of SSE streams.
- `stateless_http=True`: Creates a completely fresh transport for each request with no session tracking.

Combined, `FastMCP("name", stateless_http=True, json_response=True)` gives a server that accepts each POST independently with no session state, returns plain JSON, and requires no `Mcp-Session-Id` header.

**4. The MCP spec makes sessions optional**

Per the spec: "A server using the Streamable HTTP transport MAY assign a session ID at initialization time" [48]. Session management is explicitly optional.

**5. Raw HTTP approach: bypassing the MCP SDK transport entirely**

Since MCP uses standard JSON-RPC 2.0 over HTTP POST, you can bypass the SDK's transport layer with `httpx` or `aiohttp` [49][50][51]. Key payloads:

Initialize request:
```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize",
 "params": {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
            "clientInfo": {"name": "my-client", "version": "1.0.0"}}}
```

Tool call:
```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/call",
 "params": {"name": "tool_name", "arguments": {"arg": "value"}}}
```

When the server is configured with `stateless_http=True` and `json_response=True`, each POST returns plain JSON [51][52].

**6. httpx avoids the problematic anyio patterns**

A minimal `httpx.AsyncClient` wrapper avoids the SDK's `anyio.create_task_group()` machinery. While `httpx` itself depends on `anyio`, it uses it internally in a self-contained way that does not create competing task groups in user space [46].

**7. The `aiohttp-mcp` package still depends on anyio**

Despite being built on `aiohttp`, the `aiohttp-mcp` package still requires `anyio >= 4.9.0` because it wraps the official `mcp` SDK [53].

**8. Future: MCP is moving toward fully stateless protocol**

The MCP Transport Working Group published a roadmap (December 2025) to make the protocol fundamentally stateless [54]: replace the `initialize` handshake entirely, add a discovery endpoint, remove sticky session requirements. Spec Enhancement Proposals targeted for Q1 2026, next spec release tentatively June 2026.

**9. Key finding: the conflict is specifically with `anyio.create_task_group()`**

The core issue is not that `anyio` is imported, but that the MCP SDK transports create `anyio.create_task_group()` contexts that assume control over task scheduling. The raw HTTP approach sidesteps this because `httpx.AsyncClient` uses anyio internally but in a self-contained way [46].

---

## Synthesis Summary

The research reveals a well-documented but fundamentally unresolved conflict between the MCP Python SDK's use of anyio structured concurrency and asyncio-based frameworks like LangGraph. The MCP SDK enforces strict LIFO cleanup ordering via anyio cancel scopes and task groups, while asyncio (and frameworks built on it) allow more flexible resource management. This manifests as `RuntimeError` exceptions during session teardown and `CancelledError` cascades during timeout handling.

Four viable integration strategies emerge, ordered by decreasing isolation from the conflict:

1. **Raw httpx JSON-RPC** (Solution 1): Bypass the MCP SDK transport entirely by sending JSON-RPC POST requests directly to a stateless MCP server (`stateless_http=True, json_response=True`). This eliminates all anyio task group conflicts while maintaining full MCP protocol compatibility. Requires the server to support stateless mode.

2. **Background thread with dedicated event loop** (Solution 2): Run the MCP SDK in a separate thread with its own event loop, bridging calls via `asyncio.run_coroutine_threadsafe()`. Battle-tested by the Strands Agents SDK but adds complexity around health checks, context variable propagation, and shutdown sequencing.

3. **anyio BlockingPortal bridge** (Solution 3): Use anyio's first-class `BlockingPortal` or `BlockingPortalProvider` to bridge between threads. Cleaner than raw threading but still adds a thread boundary and is primarily designed for sync-to-async bridging rather than async-to-async.

4. **langchain-mcp-adapters ephemeral sessions** (Solution 4): Use the official adapter library with ephemeral (per-call) sessions. This works for stateless MCP servers but creates a new session per tool call, adding latency, and still uses anyio internally so LIFO cleanup issues can surface.

For CommandClaw specifically, Solution 1 (raw httpx) is recommended because the MCP gateway already supports `stateless_http` mode, eliminating the need for session management entirely. This is the simplest, most maintainable approach with zero anyio exposure in user code.
