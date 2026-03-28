# MCP Gateway Testing — Notes

## General Understanding

### Q1: How do FastMCP and mcp-proxy test their MCP protocol implementations?

#### 1. In-Memory Transport: The Core Testing Primitive

Both FastMCP and the official Python SDK center their test strategies on **in-memory transports** that bypass network I/O entirely. The official Python SDK provides `create_connected_server_and_client_session` from `mcp.shared.memory`, which creates a directly-connected `Server`/`ClientSession` pair [1]. FastMCP wraps this further: you can pass a `FastMCP` server instance directly to `Client(mcp_server)` and it automatically uses an in-process transport with no subprocess management [2][3].

Key pattern from FastMCP:
```python
async with Client(mcp_server) as client:
    result = await client.call_tool("add", {"a": 1, "b": 2})
    assert isinstance(result[0], TextContent)
    assert result[0].text == "3"
```

Important caveat from the FastMCP blog: **do not wrap `Client` in a pytest fixture** because pytest's async fixtures and test functions may run in different event loops, causing task cancellation errors. Instantiate the client within each test function [3].

#### 2. mcp-proxy's Dual-Mode Parity Testing (The Standout Pattern)

The most reusable testing pattern comes from `sparfenyuk/mcp-proxy`. Their `test_proxy_server.py` uses **parametrized session generators** to run the exact same test code against both a direct connection and a proxied connection [4]:

```python
# Direct: uses mcp.shared.memory.create_connected_server_and_client_session
in_memory: SessionContextManager = create_connected_server_and_client_session

# Proxied: wraps the server in a proxy, then connects again via in-memory
@asynccontextmanager
async def proxy(server: Server[object]) -> AsyncGenerator[ClientSession, None]:
    async with in_memory(server) as session:
        wrapped_server = await create_proxy_server(session)
        async with in_memory(wrapped_server) as wrapped_session:
            yield wrapped_session

@pytest.fixture(params=["server", "proxy"])
def session_generator(request) -> SessionContextManager:
    if request.param == "server":
        return in_memory
    return proxy
```

Every test accepts `session_generator` and calls `async with session_generator(server) as session`. This guarantees **behavioral parity** between direct and proxied paths. The test suite covers: list_prompts, list_tools, call_tool, call_tool error paths, list_resources, list_resource_templates, get_prompt, read_resource, subscribe/unsubscribe, set_logging_level, send_progress_notification, and completions [4].

#### 3. mcp-proxy's Capability-Gated Negative Testing

A subtle but important pattern: mcp-proxy tests verify that **capabilities not registered on the server are correctly absent through the proxy**. For example, when only prompts are registered, the test asserts `not result.capabilities.tools` and then verifies `pytest.raises(McpError, match="Method not found")` when calling `session.list_tools()` [4]. This validates that `create_proxy_server` correctly inspects capabilities during initialization and only registers handlers for what the backing server supports [5].

#### 4. mcp-proxy's Callback Mock Pattern

Tests use `@pytest.mark.parametrize("tool_callback", [AsyncMock()])` to inject mock callbacks via parametrize rather than fixtures. This pattern allows the test to set `.return_value` and `.side_effect` within the test body and assert `.assert_called_once_with(...)` after each operation. After each assertion, `callback.reset_mock()` is called for clean state [4].

For error testing, `tool_callback.side_effect = Exception("Error")` is set and the test verifies `call_tool_result.isError` is `True` [4].

#### 5. FastMCP's Proxy Test Architecture

FastMCP has three distinct proxy test suites [6]:

- **`tests/server/mount/test_proxy.py`** -- Tests mounting a proxied server into a parent server. Validates namespaced tool access, dynamic tool addition, resource and prompt propagation through proxy mounts. Also tests `as_proxy` kwarg behavior: when `True` it wraps with `FastMCPProxy`, when `False` it wraps with `Namespace` transform. Tests that `as_proxy` is ignored for already-proxied servers.

- **`tests/server/providers/proxy/test_proxy_server.py`** -- Tests the proxy provider layer: tool metadata forwarding, resource reading (single/multi-content), resource template resolution, prompt rendering (including `ImageContent` serialization round-trip), cache TTL behavior (TTL=0 forces fresh fetch, positive TTL reuses), and enable/disable raising `NotImplementedError`.

- **`tests/server/providers/proxy/test_proxy_client.py`** -- Tests the `ProxyClient` which handles advanced interactions: root directory forwarding, sampling parameter forwarding, elicitation workflows (accept/decline/default values), logging message forwarding, progress reporting. Tests concurrent request isolation: `test_concurrent_log_requests_no_mixing` and `test_concurrent_elicitation_no_mixing` verify no cross-contamination between simultaneous handlers.

- **`tests/server/providers/proxy/test_stateful_proxy_client.py`** -- Tests `StatefulProxyClient` for session-aware proxies: state persistence within sessions, state isolation in stateless HTTP mode, namespace isolation with multiple proxy mounts, and a regression test for elicitation over HTTP not hanging due to stale `request_ctx` ContextVar values [6].

#### 6. FastMCP's Test Utility Module (`fastmcp.utilities.tests`)

This module provides four reusable utilities [7]:

- **`temporary_settings(**kwargs)`** -- Context manager to temporarily override FastMCP settings (deepcopy + restore pattern).

- **`run_server_in_process(server_fn, *args, host, port)`** -- Starts a server in a `multiprocessing.Process`, polls with exponential backoff (50ms -> 100ms -> 200ms, max 30 attempts) until the TCP port is accepting connections, yields the URL, then terminates/kills the process.

- **`run_server_async(server, port, transport, path)`** -- Starts a server as an `asyncio.Task`, waits on `server._started` event, yields URL, then cancels the task. Used extensively in HTTP transport integration tests.

- **`HeadlessOAuth(mcp_url)`** -- Subclass of `OAuth` that replaces browser interaction with `httpx` HTTP calls for automated OAuth testing. Stores the redirect response and parses auth code + state from Location header.

#### 7. Official Python SDK Testing Patterns

The SDK's `tests/client/conftest.py` provides a **stream spy infrastructure** [8]:

- **`SpyMemoryObjectSendStream`** -- Wraps `MemoryObjectSendStream` to intercept and record all messages while forwarding them.
- **`StreamSpyCollection`** -- Manages client/server spy pairs with methods: `get_client_requests(method=)`, `get_server_requests(method=)`, `get_client_notifications(method=)`, `get_server_notifications(method=)`, and `clear()`.
- **`stream_spy` fixture** -- Patches `mcp.shared.memory.create_client_server_memory_streams` to inject spies.

The SDK uses **inline-snapshot testing** extensively via `snapshot()` assertions for comparing entire result structures against baselines [9]. The root conftest is minimal: just sets `anyio_backend` to `"asyncio"` [8].

#### 8. FastMCP Conformance Testing

FastMCP maintains a `tests/conformance/expected-failures.yml` tracking known spec compliance gaps: `completion-complete`, `server-sse-polling`, `resources-subscribe`, `resources-unsubscribe`, and `dns-rebinding-protection` [10]. This suggests they run against an external conformance test suite.

#### 9. mcp-proxy's Integration Testing (`test_mcp_server.py`)

This file tests the HTTP layer with actual Uvicorn servers [11]:

- **`BackgroundServer`** -- A `uvicorn.Server` subclass that runs in background threads with suppressed signal handlers.
- **`create_starlette_app()`** -- Factory for Starlette apps with optional CORS middleware.
- **`make_background_server()`** -- Creates a server with a test prompt ("prompt1") and echo tool.
- Integration tests: `test_sse_transport()`, `test_http_transport()`, `test_stateless_http_transport()`.
- Unit tests for `run_mcp_server()`: validates behavior with no servers configured, default server setup, named servers, CORS middleware, custom headers, debug/stateless modes, uvicorn config, global status updates, SSE URL logging, and exception handling.
- Uses `setup_async_context_mocks()` helper returning a tuple of mocks for consistent test setup.

#### 10. What to Mock vs. Test Live

Across all three projects [3][12]:

**Test live (through the protocol)**: Tool registration/discovery, parameter validation, tool execution, resource listing/reading, prompt rendering, capability negotiation, error propagation, progress notifications, sampling, elicitation, subscription lifecycle.

**Mock**: External HTTP APIs (`aiohttp.ClientSession.get`), file system operations, databases (use in-memory SQLite), time-dependent operations, OAuth browser flows (use `HeadlessOAuth`), LLM API calls.

#### 11. Reusable Testing Utilities Summary

For someone building an MCP gateway, the most directly reusable patterns are:

1. **mcp-proxy's `session_generator` parametrize pattern** -- Guarantees proxy behavioral parity with zero test duplication [4]
2. **`mcp.shared.memory.create_connected_server_and_client_session`** -- The SDK's built-in in-memory transport factory [1]
3. **FastMCP's `run_server_async`** -- For HTTP transport integration tests without subprocess overhead [7]
4. **The SDK's `StreamSpyCollection`** -- For inspecting raw JSON-RPC messages at the protocol level [8]
5. **`inline-snapshot`** -- For snapshot-based regression testing of tool schemas and response shapes [9]

---

### Q2: What are the patterns for testing async Python security middleware?

#### 1. Testing ASGI Middleware in Isolation: TestClient vs httpx.AsyncClient

There are two primary approaches for testing ASGI middleware in FastAPI/Starlette applications, and they serve different needs.

**Starlette TestClient (synchronous tests):** The TestClient wraps `httpx.Client` and bridges synchronous test code to the async ASGI application via `anyio.start_blocking_portal()` [13]. You create a minimal Starlette app with only the middleware under test and a trivial stub endpoint, then assert on response status, headers, and body. This is the pattern Starlette itself uses in its own test suite -- each test creates a purpose-built app with only the relevant middleware attached to a `PlainTextResponse` endpoint [14]:

```python
app = Starlette(
    routes=[Route("/", endpoint=lambda r: PlainTextResponse("OK"))],
    middleware=[Middleware(YourSecurityMiddleware, config=test_config)]
)
client = TestClient(app)
response = client.get("/", headers={"Authorization": "Bearer bad"})
assert response.status_code == 401
```

**httpx.AsyncClient with ASGITransport (async tests):** When your middleware calls async dependencies (e.g., async nonce cache, async policy engine), you need tests that run in the same event loop. Use `httpx.AsyncClient(transport=ASGITransport(app=app))` with `@pytest.mark.anyio` [15]. Critical caveat: `AsyncClient` does **not** trigger lifespan events; if your middleware initializes resources in lifespan, wrap with `asgi_lifespan.LifespanManager` [15].

```python
@pytest.mark.anyio
async def test_middleware_async():
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/protected")
    assert response.status_code == 403
```

**Pure ASGI middleware vs BaseHTTPMiddleware:** For security middleware, pure ASGI middleware (`__init__(self, app)` + `async __call__(self, scope, receive, send)`) is strongly recommended over `BaseHTTPMiddleware` because the latter breaks `contextvars.ContextVar` propagation [16]. Pure ASGI middleware can short-circuit by sending a response directly without calling `self.app(scope, receive, send)`, which is the natural pattern for deny-by-default enforcement. Starlette's own built-in middleware uses pure ASGI [16].

#### 2. Middleware vs Dependency Injection for Security Enforcement

FastAPI's recommended default is dependency injection via `Depends()` with `dependency_overrides` for testing [17][18]. However, a FastAPI core collaborator (Kludex) acknowledged there is no strict prohibition against middleware, and for applications where "all but one or two routes require auth," middleware can simplify enforcement [19].

**Testing tradeoff:** Dependencies are trivially mockable via `app.dependency_overrides[original_dep] = mock_dep` -- all sub-dependencies of the overridden function are skipped, and cleanup is `app.dependency_overrides = {}` [17]. Middleware, by contrast, requires either providing valid credentials or constructing an app instance without the middleware attached.

**Hybrid pattern for security middleware:** Use middleware for the cross-cutting gate (HMAC verification, token validation) and dependencies for fine-grained authorization (RBAC checks). The middleware sets `request.state.authenticated_principal` and the dependency reads it. Tests can then either test the middleware in isolation with a stub app, or override the dependency to skip authentication entirely when testing authorization logic [18][20].

#### 3. Testing HMAC Signature Verification

HMAC middleware testing requires covering four distinct verification axes [21]:

**Canonical string building:** Test that the canonical string is assembled identically on both sides. The canonical form is typically `METHOD\nPATH\nSORTED_QUERY\nTIMESTAMP\nNONCE\nBODY_HASH`. Sort query parameters lexicographically and SHA-256 hash the body rather than signing it directly. Test with edge cases: empty body, query params with special characters, trailing slashes on paths [21].

**Timestamp tolerance:** Test boundary conditions around the tolerance window (typically 300 seconds). Generate requests with `now - tolerance - 1` (should reject), `now - tolerance` (should accept), `now + tolerance` (should accept), `now + tolerance + 1` (should reject). Use `freezegun` or `unittest.mock.patch` on `datetime.utcnow` to make these deterministic [21].

**Nonce replay prevention:** Test that a second request with the same nonce is rejected with 401. The `NonceCache` should use an `OrderedDict` with TTL-based expiry. Test cache eviction: after the tolerance window passes, old nonces should be cleaned up and the same nonce value should be reusable [21].

**Constant-time comparison:** Use `hmac.compare_digest()` exclusively -- never `==`. Naive Python implementations of constant-time comparison (XOR + OR loop) fail because CPython's arbitrary-precision integer operations are inherently data-dependent [22]. The `compare_digest` function delegates to C-level code operating on machine-word primitives. Testing constant-time properties statistically requires isolating CPU cores, disabling frequency scaling, collecting 128+ samples, and using Kolmogorov-Smirnov tests to detect distribution differences [22]. For practical purposes, **lint for `hmac.compare_digest` usage** (e.g., via precli rule PY005 or a custom AST check) rather than attempting runtime timing measurements in CI [23].

```python
def test_replay_attack_prevented():
    nonce = str(uuid.uuid4())
    headers = build_hmac_headers(nonce=nonce, timestamp=now_iso())
    response1 = client.post("/secure", headers=headers, content=b'{"x":1}')
    assert response1.status_code == 200
    response2 = client.post("/secure", headers=headers, content=b'{"x":1}')
    assert response2.status_code == 401
```

#### 4. Testing RBAC Enforcement with Mocked Policy Engines

Three major integration patterns exist for external policy engines, each with distinct testing strategies:

**Cerbos:** Integrates via a Python SDK making REST/gRPC calls to a PDP sidecar. Authorization policies are written in YAML and tested independently using `cerbos compile` which auto-discovers `_test.yaml` files alongside policies [24]. Test fixtures define principals (with roles and attributes), resources, and expected `EFFECT_ALLOW`/`EFFECT_DENY` outcomes per action. For application-level tests, mock the Cerbos client's `check` method:

```python
@pytest.fixture
def mock_cerbos(monkeypatch):
    async def fake_check(principal, resource, action):
        return action in allowed_actions_for[principal.roles[0]]
    monkeypatch.setattr(cerbos_client, "check", AsyncMock(side_effect=fake_check))
```

Cerbos policies can be tested in CI via GitHub Actions (`cerbos-setup-action` + `cerbos-compile-action`) without running the full application [24].

**OPA (Open Policy Agent):** The `fastapi-opa` package provides `OPAMiddleware` that intercepts requests, extracts context (path, method, roles from headers/tokens), and POSTs to OPA's `/v1/data/` endpoint [25][26]. The OPA adapter uses `httpx.AsyncClient` internally, making it mockable via `respx` or `pytest-httpx`. For integration tests, run OPA in Docker and test policies directly with curl against the OPA REST API [27]. OPA policies (Rego) have their own test framework (`opa test`), and the `fastapi-opa` package supports `Injectable` classes for custom payload enrichment [26].

```python
# Mock OPA for unit tests
@pytest.fixture
def mock_opa(respx_mock):
    respx_mock.post("http://opa:8181/v1/data/authz").mock(
        return_value=httpx.Response(200, json={"result": {"allow": False}})
    )
```

**Model-agnostic enforcement (recommended pattern):** Keep the enforcement layer thin and policy-model-agnostic [28]. Use `pytest.mark.parametrize` to test the permission matrix exhaustively:

```python
@pytest.mark.parametrize("role,action,allowed", [
    ("admin", Action.WRITE_REPORT, True),
    ("viewer", Action.WRITE_REPORT, False),
    ("viewer", Action.READ_REPORT, True),
])
def test_role_permissions(role, action, allowed):
    user = make_user(role=role)
    if allowed:
        authorize(user, action)
    else:
        with pytest.raises(PermissionError):
            authorize(user, action)
```

#### 5. Testing Deny-by-Default Behavior

The "deny-by-default" principle means that if the policy system cannot reach a decision, the answer is "no" [28]. Testing this requires:

- **No credentials at all:** Request without any auth headers must return 401/403.
- **Malformed credentials:** Invalid HMAC format, truncated JWT, garbled base64.
- **Valid auth, no permission:** Authenticated user requesting a resource they have no explicit grant for.
- **Policy engine unavailable:** When OPA/Cerbos is unreachable, the middleware must deny (not allow). Mock the policy engine to raise `ConnectionError` and assert 503 or 403.
- **Tenant boundary tests:** User from org A must not access org B resources, even if they have the same role [28].

For middleware specifically, the Starlette pattern is to create a `TestClient(app, raise_server_exceptions=False)` to test that error responses are returned correctly rather than raising unhandled exceptions [13].

#### 6. Async Mocking Patterns

When mocking async auth backends, use `unittest.mock.AsyncMock` (stdlib since Python 3.8) rather than third-party `asyncmock` [29]. AsyncMock supports `return_value`, `side_effect`, and assertion methods identically to synchronous Mock. For patching async methods on classes:

```python
from unittest.mock import AsyncMock, patch

@patch("app.auth.verify_token", new_callable=AsyncMock, return_value={"sub": "user123"})
async def test_authenticated_request(mock_verify):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/protected", headers={"Authorization": "Bearer tok"})
    assert response.status_code == 200
    mock_verify.assert_called_once_with("tok")
```

For mocking outbound HTTP calls to policy engines, `respx` and `pytest-httpx` both work. `respx` provides route-pattern matching and is more ergonomic for mocking specific endpoints [30].

#### 7. Authenticated Test Client Fixture Pattern

A practical pattern from the OddBird guide creates a reusable fixture that handles authentication transport [20]:

```python
@pytest.fixture
def client(db):
    user = create_user(db)
    token = create_access_token(user)
    c = TestClient(app)
    c.user = user
    c.headers["Authorization"] = f"Bearer {token}"
    yield c
    app.dependency_overrides.clear()
```

This pattern attaches the user object to the client for convenient assertion access (`client.user.id`), handles cleanup, and works with transaction-rollback database isolation [20].

---

### Q3: How do you set up integration tests for MCP servers?

#### 1. The Official MCP Python SDK Test Infrastructure

The official `modelcontextprotocol/python-sdk` repository enforces **100% code coverage including branch coverage** and organizes tests under `tests/` with subdirectories: `cli/`, `client/`, `server/`, `shared/`, `experimental/`, and `issues/` [31]. All async tests use **anyio** (never raw asyncio), and the team avoids fixed `anyio.sleep()` durations, preferring `anyio.fail_after(5)` timeout guards and event-driven synchronization [31].

The SDK's transport abstraction is key to testability: every transport (stdio, SSE, StreamableHTTP, WebSocket) produces a uniform `(MemoryObjectReceiveStream[SessionMessage], MemoryObjectSendStream[SessionMessage])` pair. This means you can test the full protocol without any network or subprocess by creating **anyio in-memory object streams** directly [32]:

```python
from anyio import create_memory_object_stream

server_read, client_write = create_memory_object_stream()
client_read, server_write = create_memory_object_stream()

async with ClientSession(client_read, client_write) as session:
    await session.initialize()
    tools = await session.list_tools()
    result = await session.call_tool("add", {"a": 5, "b": 3})
```

The SDK provides a utility function `create_connected_server_and_client_session()` that wires up a `(ClientSession, ServerSession)` pair connected via in-memory streams, allowing end-to-end protocol testing (initialize handshake, capability negotiation, request/response correlation) without transport details [31].

**Key test dependencies** from the SDK's `pyproject.toml` [31]:
- `pytest>8.3.4`, `trio>0.26.2` (alternative anyio backend), `pytest-xdist>3.6.1` (parallel execution)
- `inline-snapshot>0.23.0` (snapshot-based output validation)
- `dirty-equals>0.9.0` (flexible equality for dynamic values like timestamps/UUIDs)
- `coverage[toml]>7.10.7` (enforced at 100%)

#### 2. FastMCP's In-Memory Test Client (Recommended for Most Projects)

FastMCP (by Jlowin/Prefect) provides the most ergonomic testing story. The `Client` class accepts a `FastMCP` server instance directly as its transport, establishing an **in-memory connection** that uses the real MCP protocol internally without subprocess or network overhead [2][3]:

```python
from fastmcp import FastMCP, Client

mcp = FastMCP(name="TestServer")

@mcp.tool()
def add(a: int, b: int) -> int:
    return a + b

# In-memory test -- no subprocess, no HTTP, but full protocol fidelity
async with Client(mcp) as client:
    tools = await client.list_tools()
    result = await client.call_tool("add", {"a": 1, "b": 2})
    assert result.data == 3
```

The recommended pytest pattern (per Jlowin's blog post) is to **instantiate the `Client` inside each test function** rather than in a fixture, to avoid event loop conflicts [3]:

```python
import pytest
from fastmcp import FastMCP, Client
from mcp.types import TextContent

@pytest.fixture
def mcp_server():
    mcp = FastMCP(name="CalculationServer")
    @mcp.tool()
    def add(a: int, b: int) -> int:
        return a + b
    return mcp

async def test_add_tool(mcp_server: FastMCP):
    async with Client(mcp_server) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert isinstance(result[0], TextContent)
        assert result[0].text == "3"
```

The `Client` also works universally with remote servers and subprocess-based servers [3]:

```python
# Remote Streamable HTTP server
async with Client("http://some.api.service/mcp_endpoint") as client:
    await client.call_tool("some_tool", {"key": "value"})

# Local subprocess via MCP config (like Claude Desktop config)
async with Client({"mcpServers": {"github": {"command": "npx", "args": [...]}}}) as client:
    await client.call_tool("github_get_user_repos", {"username": "jlowin"})
```

Available `Client` methods for testing [3][12]:
- `await client.ping()` -- server availability
- `await client.list_tools()` -- tool discovery
- `await client.call_tool("name", {"param": value})` -- tool invocation
- `await client.list_resources()` / `await client.read_resource("resource://path")` -- resource access
- `await client.list_prompts()` / `await client.get_prompt("name", {"arg": "val"})` -- prompt rendering

#### 3. FastMCP Test Utilities Module

FastMCP ships a dedicated `fastmcp.utilities.tests` module with four utilities [7]:

1. **`temporary_settings(**kwargs)`** -- Context manager that temporarily overrides FastMCP settings for test isolation.

2. **`run_server_in_process(server_fn, *args, host, port)`** -- Spawns a FastMCP server in a separate `multiprocessing.Process`, polls until the port is connectable (up to 30 attempts with backoff), yields `http://{host}:{port}`, then terminates the process. Useful for integration tests requiring actual HTTP transport.

3. **`run_server_async(server, port, transport, path)`** -- Starts a FastMCP server as an `asyncio.Task` within the same process. Supports `"http"`, `"streamable-http"`, and `"sse"` transports. Uses `server._started` event to synchronize. This is the **recommended approach for async integration tests** that need real HTTP.

4. **`HeadlessOAuth(mcp_url)`** -- Simulates the complete OAuth authorization code flow programmatically (no browser), for testing authenticated MCP endpoints.

Example using `run_server_async` for a full Streamable HTTP integration test:

```python
from fastmcp import FastMCP, Client
from fastmcp.utilities.tests import run_server_async

async def test_streamable_http_round_trip():
    server = FastMCP("TestServer")
    @server.tool()
    def greet(name: str) -> str:
        return f"Hello, {name}"

    async with run_server_async(server, transport="streamable-http") as url:
        async with Client(url) as client:
            result = await client.call_tool("greet", {"name": "World"})
            assert result.data == "Hello, World"
```

#### 4. Testing the Initialize Handshake

The MCP lifecycle begins with a mandatory initialization handshake [33][32]:

1. Client sends `InitializeRequest` with `protocolVersion`, `capabilities`, and `clientInfo`
2. Server responds with `InitializeResult` containing its `protocolVersion`, `capabilities`, and `serverInfo`
3. Client validates the protocol version is supported
4. Client sends `InitializedNotification` to complete the handshake

**Wire format** [34]:
```json
// Client -> Server
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{"roots":{"listChanged":true},"sampling":{}},"clientInfo":{"name":"TestClient","version":"1.0.0"}}}

// Server -> Client
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{},"resources":{"subscribe":true}},"serverInfo":{"name":"test-server","version":"1.0.0"}}}

// Client -> Server (notification, no id)
{"jsonrpc":"2.0","method":"notifications/initialized"}
```

With `ClientSession`, `await session.initialize()` handles this entire sequence automatically, including capability negotiation and version validation. After initialization, `session.server_capabilities` exposes what the server advertised [32].

**Testing the handshake directly** (for a gateway that needs to validate raw JSON-RPC):
```python
async def test_initialize_handshake():
    async with Client(mcp_server) as client:
        # Client() already calls initialize() internally
        # Verify server capabilities were negotiated
        tools = await client.list_tools()
        assert len(tools) > 0  # Server advertised tools capability
```

For low-level testing, send raw JSON-RPC over stdio:
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}}' | python -m my_server
```

#### 5. Testing Stdio Transport (Subprocess stdin/stdout)

The stdio transport spec [33]:
- Client launches server as a subprocess
- Messages are newline-delimited JSON-RPC on stdin/stdout
- Messages MUST NOT contain embedded newlines
- stderr is for logging only; stdout is exclusively for MCP messages

**Using the official SDK's `stdio_client`** [35]:
```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import AsyncExitStack

async def test_stdio_round_trip():
    exit_stack = AsyncExitStack()
    read, write = await exit_stack.enter_async_context(
        stdio_client(StdioServerParameters(
            command="python",
            args=["-m", "my_mcp_server"],
            env=None,
        ))
    )
    session = await exit_stack.enter_async_context(
        ClientSession(read, write)
    )
    await session.initialize()

    tools = await session.list_tools()
    assert any(t.name == "my_tool" for t in tools.tools)

    result = await session.call_tool("my_tool", {"arg": "value"})
    assert result.content[0].text == "expected"

    await exit_stack.aclose()
```

**Key testing considerations for stdio** [36]:
- Performance: <1ms latency, 10,000+ ops/sec -- tests are fast
- Unhandled exceptions crash the subprocess, so test error boundaries carefully
- Debug output MUST go to stderr; any non-JSON on stdout breaks the protocol
- Windows vs Unix process handling differs (pywin32 needed on Windows)

#### 6. Testing Streamable HTTP Transport

The Streamable HTTP transport operates over a single HTTP endpoint (e.g., `/mcp`) supporting POST and GET methods [33]:

- **Client-to-server**: POST with JSON-RPC body, `Accept: application/json, text/event-stream`
- **Server-to-client**: Either `application/json` (single response) or `text/event-stream` (SSE stream with multiple messages)
- **Server-initiated messages**: Client opens GET to the endpoint to receive an SSE stream for notifications/requests

**Testing with httpx or curl** [36]:
```bash
curl -X POST http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

**Testing SSE streaming responses**: When the server returns `Content-Type: text/event-stream`, each SSE event contains a JSON-RPC message. The server MAY send progress notifications before the final response. Tests must handle both `application/json` and `text/event-stream` content types [33].

**Testing with FastMCP's `run_server_async`** for a real HTTP round-trip:
```python
from fastmcp.utilities.tests import run_server_async

async def test_streamable_http_with_sse():
    server = FastMCP("TestServer")
    @server.tool()
    def slow_tool(x: int) -> int:
        return x * 2

    async with run_server_async(server, transport="streamable-http") as url:
        async with Client(url) as client:
            result = await client.call_tool("slow_tool", {"x": 21})
            assert result.data == 42
```

**Two response modes** the server can use [37]:
1. **SSE Streaming Mode** (default): Returns `text/event-stream`, supports progress notifications and multiple messages per request, each message becomes an SSE event with optional ID for resumability
2. **JSON Response Mode**: Returns single `application/json`, simpler but cannot send progress notifications

#### 7. Testing Session Management (Mcp-Session-Id)

The session lifecycle for Streamable HTTP [33][38]:

1. **Creation**: Server MAY return `Mcp-Session-Id` header in the `InitializeResult` response. The ID must be globally unique, cryptographically secure, and contain only visible ASCII (0x21-0x7E).
2. **Propagation**: Client MUST include `Mcp-Session-Id` in all subsequent HTTP requests.
3. **Validation**: Server SHOULD return HTTP 400 if the header is missing on non-initialization requests.
4. **Termination**: Server MAY terminate at any time, returning HTTP 404 for subsequent requests with that session ID.
5. **Re-initialization**: Client receiving 404 MUST start a new session with a fresh `InitializeRequest`.
6. **Explicit termination**: Client SHOULD send HTTP DELETE with the session ID header when leaving.

**Test cases for session management**:

```python
import httpx

async def test_session_id_propagation(server_url):
    async with httpx.AsyncClient() as http:
        # 1. Initialize -- server returns Mcp-Session-Id
        init_resp = await http.post(server_url, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "0.1"}}
        }, headers={"Accept": "application/json, text/event-stream"})
        session_id = init_resp.headers.get("mcp-session-id")
        assert session_id is not None

        # 2. Send initialized notification with session ID
        notif_resp = await http.post(server_url, json={
            "jsonrpc": "2.0", "method": "notifications/initialized"
        }, headers={"Mcp-Session-Id": session_id,
                    "Accept": "application/json, text/event-stream"})
        assert notif_resp.status_code == 202

        # 3. Request without session ID -> 400
        bad_resp = await http.post(server_url, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list"
        }, headers={"Accept": "application/json, text/event-stream"})
        assert bad_resp.status_code == 400

        # 4. Request with session ID -> success
        tools_resp = await http.post(server_url, json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/list"
        }, headers={"Mcp-Session-Id": session_id,
                    "Accept": "application/json, text/event-stream"})
        assert tools_resp.status_code == 200

        # 5. DELETE to terminate session
        del_resp = await http.request("DELETE", server_url,
            headers={"Mcp-Session-Id": session_id})
        assert del_resp.status_code in (200, 202, 204, 405)
```

**Stateful vs Stateless modes** [37]: The `StreamableHTTPSessionManager` supports both. Stateful mode persists sessions with UUID tracking and idle timeouts; stateless mode creates a fresh transport per request (for serverless). The manager tracks active sessions in `_server_instances` dict and enforces idle timeouts via `anyio.CancelScope` deadlines.

#### 8. Testing SSE Stream Resumability

The spec supports resumable SSE via `Last-Event-ID` [33]:

1. Server MAY attach `id` fields to SSE events (must be globally unique within the session)
2. On reconnection, client sends `GET` with `Last-Event-ID` header
3. Server replays messages sent after that event ID, on the same stream only

**Test pattern for resumability**:
```python
async def test_sse_resumability(server_url, session_id):
    async with httpx.AsyncClient() as http:
        # Start a long-running tool call that streams SSE
        # Capture event IDs from the stream
        # Disconnect mid-stream
        # Reconnect with Last-Event-ID
        # Verify missed events are replayed

        resp = await http.get(server_url, headers={
            "Mcp-Session-Id": session_id,
            "Accept": "text/event-stream",
            "Last-Event-ID": "evt-42"
        })
        # Server should replay events after evt-42
```

The `EventStore` interface in the SDK has two methods [37]:
- `store_event(stream_id, message) -> event_id` -- persist and return ID
- `replay_events_after(last_event_id, send_callback)` -- replay stored events

#### 9. Testing tools/list and tools/call Round-Trips

**JSON-RPC wire format** [34]:

```json
// tools/list
{"jsonrpc":"2.0","id":3,"method":"tools/list"}
// Response:
{"jsonrpc":"2.0","id":3,"result":{"tools":[{"name":"calculate","description":"...","inputSchema":{...}}]}}

// tools/call
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"calculate","arguments":{"operation":"add","a":1,"b":2}}}
// Response:
{"jsonrpc":"2.0","id":4,"result":{"content":[{"type":"text","text":"3"}]}}
```

**Standard error codes** [34]: -32700 (parse error), -32600 (invalid request), -32601 (method not found), -32602 (invalid params), -32603 (internal error), -32000 to -32099 (server-specific).

**Comprehensive test checklist** [3][12]:
- Tool logic with valid inputs (parametrize broadly)
- Default parameter handling
- Required parameter validation (missing params -> error)
- Invalid parameter types
- Tool not found error
- Error propagation from tool implementations (RuntimeError, ValueError)
- Resource listing and retrieval
- Prompt rendering with arguments
- Async tool execution

#### 10. MCP Inspector for Manual and CI Testing

The MCP Inspector (`npx @modelcontextprotocol/inspector`) provides both a web UI and **CLI mode** [39]:

```bash
# Launch with Python server via stdio
npx @modelcontextprotocol/inspector python -m my_server

# Launch with Streamable HTTP
npx @modelcontextprotocol/inspector --transport streamablehttp --url http://localhost:8000/mcp
```

**CLI mode** outputs JSON, making it suitable for automated CI pipelines [39]. The inspector handles the initialize handshake automatically and provides tabs for tools, resources, prompts, and notifications.

The Inspector consists of two components: a React-based web UI (port 5173) and an MCP Proxy server (port 3000) that bridges the web UI to MCP servers via various transports [40].

#### 11. Low-Level Raw JSON-RPC Testing

For gateway developers who need to validate wire-level protocol compliance, raw JSON-RPC testing over both transports is essential [34][36]:

**Stdio**:
```python
import subprocess, json

proc = subprocess.Popen(
    ["python", "-m", "my_server"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
# Send initialize
proc.stdin.write(json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {},
               "clientInfo": {"name": "raw-test", "version": "0.1"}}
}).encode() + b"\n")
proc.stdin.flush()
response = json.loads(proc.stdout.readline())
assert response["result"]["protocolVersion"] == "2025-03-26"
```

**Streamable HTTP**:
```python
import httpx

async def test_raw_jsonrpc_over_http(server_url):
    async with httpx.AsyncClient() as http:
        resp = await http.post(server_url, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list"
        }, headers={"Accept": "application/json, text/event-stream"})
        body = resp.json()
        assert "result" in body
        assert "tools" in body["result"]
```

#### 12. What the SDK Does NOT Provide (Gaps)

- The official `modelcontextprotocol/python-sdk` README does not document test utilities prominently [41]. You must look at the `tests/` directory and CLAUDE.md for patterns.
- There is no official `pytest` plugin for MCP.
- The SDK's `create_connected_server_and_client_session()` is an internal test utility, not a public API [31].
- FastMCP's `Client(server)` in-memory pattern is the closest thing to a first-class test client, but it is a FastMCP feature, not part of the official SDK [2][3].
- The GitHub issue #1252 on the python-sdk confirms the community recommendation: test business logic directly, then use `Client` with in-memory transport for MCP-layer tests [42].

---

### Q4: Best practices for testing credential encryption, rotation, circuit breakers, Redis?

#### 1. Testing Fernet Encryption Round-Trips

The canonical pattern for testing Fernet encrypt/decrypt round-trips is to assert that `decrypt(encrypt(plaintext)) == plaintext` with a known key. The `cryptography` library's own test patterns validate cross-implementation consistency -- e.g., comparing `pyaes` output against `cryptography`'s AES, then testing the full Fernet pipeline with random IVs and salts [43]. Key things to test:

- **Basic round-trip**: Generate a key via `Fernet.generate_key()`, encrypt bytes, decrypt, assert equality. This is the fundamental sanity check [44].
- **InvalidToken exceptions**: Assert `cryptography.fernet.InvalidToken` is raised for malformed tokens, tampered ciphertext, and tokens encrypted with a different key. The library raises this single exception for all failure modes (bad signature, bad format, expired TTL) to avoid leaking information about *why* decryption failed [45].
- **TTL enforcement**: Use `decrypt(token, ttl=N)` to assert expiration behavior. Critically, the library provides `decrypt_at_time(token, ttl, current_time)` (added in cryptography 3.0) which accepts an explicit `current_time` integer, enabling deterministic TTL testing without any time-mocking library [45].
- **Cross-library validation**: The python-fernet test suite validates encryption output byte-for-byte between a pure-Python implementation and the `cryptography` C backend. This pattern is useful if you implement a custom Fernet wrapper [43].

**Fixture pattern**:
```python
@pytest.fixture
def fernet_key() -> bytes:
    return Fernet.generate_key()

@pytest.fixture
def fernet(fernet_key) -> Fernet:
    return Fernet(fernet_key)
```

#### 2. Testing Argon2id KDF: Mocking for Speed vs. Real for Correctness

The IBM/mcp-context-forge test plan [46] defines 12 test cases covering Argon2id, with configurable parameters: `time_cost=3`, `memory_cost=65536` (64 MB), `parallelism=1`, hash length 32 bytes, salt length 16 bytes. Key testing strategies:

- **Real Argon2id for correctness tests**: At least one test should derive a key with real Argon2id parameters and verify the output format matches `$argon2id$v=19$m=65536,t=3,p=1$<salt>$<hash>`. This catches parameter misconfiguration [46].
- **Reduced parameters for speed**: For unit tests that merely need a derived key (e.g., to feed into Fernet), use drastically reduced parameters (`time_cost=1`, `memory_cost=64`) to keep tests under 100ms. Annotate with a comment explaining the reduction [46].
- **Deterministic salt for snapshot tests**: If you need reproducible output, fix the salt via a fixture. Real code must use `os.urandom(16)` [46].
- **Unique salts**: Test that hashing the same password twice produces different hashes (TC-EN-012 in the IBM plan). This validates salt generation is non-deterministic [46].
- **Timing attack resistance**: The test plan includes TC-EN-004 which verifies constant-time comparison -- measure response times for correct vs. incorrect passwords and assert they are within a small epsilon [46].

**Speed tradeoff recommendation**: Have a small number of "integration" tests with production-strength Argon2id parameters (mark with `@pytest.mark.slow`) and a larger set of fast unit tests with minimal parameters.

#### 3. MultiFernet and Token Rotation Testing

MultiFernet is the canonical mechanism for key rotation in the `cryptography` library [45][47]. Key testing patterns:

- **Encrypt-with-old, decrypt-with-new**: Create `MultiFernet([old_key])`, encrypt a token, then create `MultiFernet([new_key, old_key])` and assert decryption succeeds. The library tries each key in order [45].
- **rotate() preserves timestamp**: `MultiFernet.rotate(token)` re-encrypts under the primary (first) key but preserves the original timestamp. Test by encrypting, sleeping or time-mocking, rotating, then using `decrypt_at_time()` to verify the original timestamp is preserved [45].
- **rotate() with retired keys**: After rotation, create a MultiFernet with only the new key and assert the rotated token decrypts successfully. Then assert the *original* (unrotated) token raises `InvalidToken` [47].
- **Key retirement workflow**: Generate key3, build `MultiFernet([key3, key1, key2])`, rotate all tokens, then drop key1 and key2. Assert old tokens fail, rotated tokens succeed [45].

#### 4. Time Mocking: freezegun vs. time-machine

For testing TTL, token expiry, and rotation schedules [48][49][50]:

- **freezegun** (`freeze_time`): Pure Python, mature (2012). Supports `tick()` for advancing time by deltas and `move_to()` for jumping to specific datetimes. Critical for async: the `real_asyncio=True` parameter allows `asyncio.sleep()` and the event loop to use real monotonic time while `datetime.now()` remains frozen [48].
- **time-machine**: C extension, 10-100x faster than freezegun in benchmarks. Uses `travel()` context manager with `shift()` and `move_to()`. Better for large test suites [49].
- **Clock pattern (DI)**: Inject a `Clock` protocol/interface into production code, supply a `FakeClock` in tests. Avoids monkey-patching entirely. Most architecturally clean but requires upfront design [50].
- **`decrypt_at_time()`**: For pure Fernet TTL testing, you don't need any time library -- pass `current_time` explicitly [45].

**Async-specific guidance**: When using freezegun with pytest-asyncio, always pass `real_asyncio=True` to avoid breaking the event loop. Without it, `asyncio.sleep()` sees frozen monotonic time and may hang or behave unpredictably [48].

```python
@freeze_time("2025-01-01", real_asyncio=True)
@pytest.mark.asyncio
async def test_token_expiry():
    token = create_token()
    # move time forward past TTL
    with freeze_time("2025-01-02"):
        with pytest.raises(InvalidToken):
            decrypt_with_ttl(token, ttl=3600)
```

#### 5. FakeRedis Fixtures and Async Patterns

FakeRedis (v2.34.1 as of Feb 2026) provides `FakeAsyncRedis` for testing without a real Redis server [51][52]. It supports all Redis commands including INCR, EXPIRE, SET, GET, SETEX, pipelines, and Lua scripting [51].

**Canonical async fixture** [52]:
```python
import fakeredis
import pytest_asyncio

@pytest_asyncio.fixture
async def redis_client():
    async with fakeredis.FakeAsyncRedis() as client:
        yield client
```

**Key fixture considerations**:
- Use `async with` for proper cleanup [52].
- For shared state across tests (e.g., testing session stores), use `connected_server` parameter to share the in-memory backing store between FakeAsyncRedis instances [51].
- For isolated tests, create a fresh `FakeAsyncRedis()` per test (the default) [51].
- The `decode_responses=True` kwarg works as expected for string-mode testing [52].

**Event loop pitfall**: When using FastAPI's dependency injection, avoid `app.dependency_overrides` with FakeAsyncRedis in synchronous test clients -- it causes event loop mismatch errors (`RuntimeError: <Queue> is bound to a different event loop`). Instead, use `mock.patch` on the module-level Redis reference combined with `httpx.AsyncClient` and fully async tests [53].

#### 6. Testing Redis INCR/EXPIRE Rate Limiting

With FakeAsyncRedis, you can test sliding-window or fixed-window rate limiters directly [51]:

```python
@pytest.mark.asyncio
async def test_rate_limiter_blocks_after_threshold(redis_client):
    key = "rate:user:123"
    for _ in range(10):
        await redis_client.incr(key)
    await redis_client.expire(key, 60)

    count = int(await redis_client.get(key))
    assert count == 10

    ttl = await redis_client.ttl(key)
    assert 0 < ttl <= 60
```

For testing expiry behavior, FakeRedis supports time advancement -- you can either wait real time (impractical) or use the `fakeredis` time utilities. An alternative is to test your rate limiter logic with a mockable clock, decoupling the Redis TTL from the rate-limit window check.

#### 7. Testing Circuit Breaker State Machines

**pybreaker (sync, with Tornado async)** [54]:

Pybreaker exposes `current_state`, `fail_counter`, `success_counter`, and manual state control (`open()`, `close()`, `half_open()`). Testing pattern:

```python
def test_circuit_opens_after_failures():
    breaker = CircuitBreaker(fail_max=3, reset_timeout=10)
    for _ in range(3):
        with pytest.raises(SomeError):
            breaker.call(failing_function)
    assert breaker.current_state == "open"
    with pytest.raises(CircuitBreakerError):
        breaker.call(some_function)
```

Use `CircuitBreakerListener.state_change` to assert transitions occur in the expected order [54].

**aiobreaker (native asyncio)** [55]:

Fork of pybreaker for async. Use `@breaker` as a decorator on async functions. Supports both sync and async listeners. Test state transitions by injecting `AsyncMock(side_effect=Exception)` as the protected function [55].

**Testing state transitions thoroughly** [56][54]:

1. **Closed -> Open**: Trigger `fail_max` consecutive failures, assert state is "open" and calls raise `CircuitBreakerError`.
2. **Open -> Half-Open**: After `reset_timeout` seconds (use time-machine/freezegun to advance), assert state is "half-open" and one call is permitted.
3. **Half-Open -> Closed**: Make the trial call succeed, assert state returns to "closed".
4. **Half-Open -> Open**: Make the trial call fail, assert state returns to "open".
5. **Exception exclusion**: Configure `exclude=[BusinessError]`, trigger that exception, assert `fail_counter` does not increment [54].

**Redis-backed circuit breaker** [56][57]:

For distributed breakers using `CircuitRedisStorage`, inject FakeRedis as the storage backend in tests. This validates that state serialization/deserialization to Redis works correctly. Do NOT initialize Redis with `decode_responses=True` as pybreaker requires bytes [54].

#### 8. Testing asyncio.to_thread for Blocking Crypto

When offloading CPU-bound crypto (Argon2id hashing, Fernet encrypt/decrypt) to a thread via `asyncio.to_thread()` [58][29]:

- **Mock the blocking function, not the threading**: Patch the synchronous function (e.g., `argon2.hash_password`) and verify it was called with correct arguments. `asyncio.to_thread` is a thin wrapper and doesn't need mocking itself [58].
- **Integration test without mocking**: Call the async wrapper, await the result, assert correctness. This validates the `to_thread` integration actually works:

```python
@pytest.mark.asyncio
async def test_async_encrypt_round_trip():
    key = Fernet.generate_key()
    plaintext = b"secret"
    ciphertext = await asyncio.to_thread(Fernet(key).encrypt, plaintext)
    result = await asyncio.to_thread(Fernet(key).decrypt, ciphertext)
    assert result == plaintext
```

- **ThreadingMock** (Python 3.12+): `unittest.mock.ThreadingMock` provides `wait_until_called()` and `wait_until_any_call_with()` for asserting cross-thread interactions [58].

#### 9. Testing Concurrent Access Patterns with asyncio.gather

For testing concurrent session pool acquire/release or concurrent credential operations [29][59]:

```python
@pytest.mark.asyncio
async def test_concurrent_session_acquire():
    pool = SessionPool(max_size=3)

    async def acquire_and_release():
        session = await pool.acquire()
        await asyncio.sleep(0.01)
        await pool.release(session)

    # Launch more tasks than pool size to test queuing
    await asyncio.gather(*[acquire_and_release() for _ in range(10)])
    assert pool.available == 3
```

**Key patterns** [29][59]:
- Use `asyncio.gather()` to launch N concurrent coroutines and assert the aggregate result.
- Use `asyncio.Semaphore` or `asyncio.Lock` in production code; test that they prevent data corruption under concurrent access.
- For race condition detection, deliberately omit synchronization and assert that invariants break (negative test).
- Use `asyncio.Event` to coordinate test tasks -- e.g., hold all tasks at a barrier, release simultaneously.

#### 10. Testing Session Pool Acquire/Release/Eviction

Session pool testing should cover [57][29]:

- **Acquire within capacity**: Assert a session is returned immediately when the pool has available slots.
- **Acquire at capacity**: Assert the coroutine blocks (use `asyncio.wait_for` with a short timeout and assert `TimeoutError`).
- **Release returns to pool**: Acquire, release, assert `pool.available` increments.
- **Eviction on idle timeout**: Use time-mocking to advance past the idle timeout, trigger a health check or eviction sweep, assert the session is removed.
- **Eviction on error**: Inject a broken session (mock returning errors), assert it is evicted rather than returned to the pool.
- **Concurrent acquire/release**: Use `asyncio.gather` as shown above to validate pool integrity under contention.

#### 11. Testing Credential Zeroing (ctypes.memset)

This is one of the hardest things to test in Python due to language-level constraints [60][61][62]:

- **Python strings are immutable**: You cannot overwrite their contents. Even `ctypes.memset(id(s) + offset, 0, len(s))` is fragile -- it depends on CPython's internal `PyUnicodeObject` layout, varies across Python versions, and can segfault [60].
- **Use `bytearray` for mutable secrets**: Store credentials in `bytearray`, zero with `for i in range(len(ba)): ba[i] = 0` or `ctypes.memset(ctypes.addressof((ctypes.c_char * len(ba)).from_buffer(ba)), 0, len(ba))`. This is the only reliable approach in pure Python [60].
- **`ctypes.c_char_p` buffers**: Allocate with `ctypes.create_string_buffer(secret)`, use the buffer, then `ctypes.memset(buf, 0, len(buf))`. More controllable than bytearray [60].
- **Testing verification**: The only reliable way to verify zeroing is to inspect the memory region after clearing. Use `ctypes.string_at(address, length)` and assert all bytes are `\x00`. This is inherently CPython-specific [60][61].

```python
def test_credential_zeroing():
    buf = ctypes.create_string_buffer(b"supersecret")
    addr = ctypes.addressof(buf)
    length = len(buf)

    ctypes.memset(addr, 0, length)

    content = ctypes.string_at(addr, length)
    assert content == b"\x00" * length
```

- **Caveat**: The CPython GC may have already copied the secret elsewhere (string interning, internal buffers). Zeroing one location does not guarantee the secret is gone from all of process memory [60][61]. The `pyca/cryptography` team closed the secure-wipe feature request after 8 years, noting that OS-level memory swapping further undermines the guarantee [62].
- **Practical recommendation**: Use `bytearray` or `ctypes` buffers for secret material from the start. Never convert to `str`. Accept that Python cannot provide the same guarantees as C/Rust for memory zeroing, and document this limitation in your threat model [60][62].

---

### Summary

Four dominant themes emerge across all research questions. First, **in-memory transports are the universal testing primitive** for MCP: the official SDK's `create_connected_server_and_client_session`, FastMCP's `Client(server)`, and mcp-proxy's parametrized session generators all eliminate network I/O while preserving full protocol fidelity, enabling fast, deterministic tests of the complete JSON-RPC lifecycle including initialization, capability negotiation, and tool/resource/prompt operations. Second, **parametrized parity testing** (running identical assertions against both direct and proxied/middlewared paths) is the gold standard for gateway and proxy code, as demonstrated by mcp-proxy's `session_generator` fixture and the hybrid middleware/dependency-injection pattern for security layers. Third, **async testing in Python requires deliberate attention to event loop boundaries**: avoid sharing async resources across fixtures and test functions in different loops, use `real_asyncio=True` with freezegun, prefer `anyio.fail_after` over `asyncio.sleep`, and use `httpx.AsyncClient` with `ASGITransport` rather than synchronous test clients when middleware has async dependencies. Fourth, **mock at the boundary, test live through the protocol**: external HTTP APIs, policy engines, Redis, and time should be mocked (using FakeAsyncRedis, respx, freezegun/time-machine, or `decrypt_at_time`), while MCP protocol semantics, HMAC verification logic, Fernet round-trips, and circuit breaker state machines should be tested with real implementations to catch integration bugs that mocks would hide.

---

## Deeper Dive
### Subtopic 1: MCP Protocol Compliance Testing

#### From DD1: MCP Protocol Constraints Requiring Automated Verification

### 1. JSON-RPC Message ID Preservation and Correlation

The MCP specification mandates strict JSON-RPC 2.0 message ID handling with MCP-specific constraints that a gateway must preserve transparently [63]:

- Request IDs **MUST** be string or integer; unlike base JSON-RPC, **MUST NOT** be `null` [63].
- The request ID **MUST NOT** have been previously used by the requestor within the same session -- a gateway that rewrites IDs (e.g., to multiplex upstream connections) must maintain a bijective mapping and enforce session-scoped uniqueness on both legs [63].
- Responses **MUST** include the same ID as the corresponding request. Error responses equally require the original ID for proper correlation [63]. A gateway that fans out to multiple backends must correctly route responses back by ID, never dropping or swapping IDs.
- Notifications **MUST NOT** include an ID. A gateway must not inject IDs into forwarded notifications, nor strip IDs from requests [63].

**Automated verification approach:** Inject requests with known IDs through the gateway, verify response IDs match exactly. Test edge cases: integer IDs, string IDs, large numeric IDs near JSON precision limits, and verify the gateway rejects `null` IDs rather than passing them through.

### 2. Batch Request Handling (Removal in 2025-06-18)

The 2025-06-18 spec **removes JSON-RPC batch request support** -- each JSON-RPC call must be sent as its own message (one JSON object per request, not an array) [64]. This is a breaking change from standard JSON-RPC 2.0 behavior.

A gateway must:
- Reject incoming JSON arrays with an appropriate error for 2025-06-18 sessions [65].
- Potentially accept batches from older clients (2024-11-05, 2025-03-26) if supporting backward compatibility [64].
- The MCP Validator explicitly tests that "batch requests are properly rejected for 2025-06-18 protocol" [65].

**Automated verification:** Send JSON arrays to the gateway endpoint under each protocol version, assert rejection for 2025-06-18 and correct handling for older versions.

### 3. Capability Negotiation Integrity

The initialization handshake is a strict three-phase sequence: `initialize` request, `initialize` response, `notifications/initialized` notification. Until this completes, no functional requests may occur [66]:

- The client sends its `protocolVersion` and `capabilities`; the server responds with its own. If versions are incompatible, the client **SHOULD** disconnect [66].
- A gateway sitting between client and server faces a critical design decision: does it perform its own capability negotiation with each side independently (split handshake), or transparently forward the handshake (passthrough)? In either case, the negotiated capabilities constrain the entire session [66].
- The client **SHOULD NOT** send non-ping requests before the server's initialize response; the server **SHOULD NOT** send non-ping/logging requests before `initialized` [66]. A gateway must enforce or at least not violate this ordering.
- Real-world capability gaps exist: clients declare capabilities they don't fully implement (e.g., `listChanged` notifications, resource subscriptions), creating a "vicious cycle" where servers must target the lowest common denominator [67]. A gateway that aggregates multiple servers must reconcile divergent server capabilities into a coherent client-facing capability set.

**Automated verification:** Test version mismatch scenarios (client sends future version, server responds with older), verify gateway correctly propagates or handles the mismatch. Test that pre-initialization requests are rejected. Test capability intersection when the gateway fronts multiple servers with different capability sets.

### 4. Protocol Version Header Enforcement

After initialization, all HTTP requests **MUST** include `MCP-Protocol-Version: <negotiated-version>` [68]. Servers **MUST** respond `400 Bad Request` to invalid or unsupported versions [68]. If the header is absent, servers should assume `2025-03-26` for backward compatibility [68].

A gateway must:
- Preserve this header on forwarded requests.
- Potentially translate between protocol versions if the client and upstream server negotiated different versions.
- Never strip or overwrite the header without understanding the implications.

**Automated verification:** Send requests with missing, incorrect, and valid `MCP-Protocol-Version` headers through the gateway. Verify correct forwarding and error responses.

### 5. SSE Resumability and Last-Event-ID

The Streamable HTTP transport's resumability mechanism has specific invariants [63][69]:

- Servers **MAY** attach `id` fields to SSE events; if present, IDs **MUST** be globally unique across all streams within a session [63].
- Event IDs should be assigned per-stream to act as a cursor within that stream. A recommended encoding is `${streamId}/${eventNumber}` to enable proper routing [70].
- On reconnection, clients **SHOULD** send `Last-Event-ID` header; servers **MAY** replay missed events *only from the disconnected stream* -- **MUST NOT** replay events from different streams [63].
- A gateway that terminates SSE on the client side and maintains its own connections upstream must implement its own event ID tracking and replay buffer, or transparently pass through SSE streams without breaking ID semantics.
- The MCP Inspector had a bug (#723) where `Last-Event-ID` was not sent on reconnect, breaking resumability entirely -- this was fixed via dynamic header injection for proxy transports [71].
- Servers can proactively disconnect after sending an event ID, using SSE `retry` field to control reconnection timing. Clients **MUST** respect the `retry` field [70]. Servers may send an initial event with an `id` and empty `data` to "prime" the client for reconnection [70].

**Automated verification:** Establish SSE stream through gateway, inject events with IDs, simulate disconnect, reconnect with `Last-Event-ID`, verify only the correct stream's events are replayed. Test that the gateway preserves event IDs and does not merge events across streams. Test the "priming" pattern (empty-data event with ID before disconnect).

### 6. Session Management Through the Gateway

Session state is tracked via `Mcp-Session-Id` header [63]:

- Server assigns session ID in the `InitializeResult` response. It **MUST** be globally unique, cryptographically secure, visible ASCII only (0x21-0x7E) [63].
- Clients **MUST** include this header on all subsequent requests. Servers **SHOULD** reject requests without it (HTTP 400) [63].
- Servers **MUST** respond HTTP 404 to expired/terminated sessions; clients **MUST** then re-initialize [63].
- Clients **SHOULD** send HTTP DELETE to terminate sessions [63].
- A gateway multiplexing sessions to multiple backends must maintain session affinity or session state replication. Envoy's MCP proxy implementation handles this via "efficient handling of stateful sessions and multi-part JSON-RPC messaging" [72].
- Token binding (RFC 8707) requires clients to bind access tokens to specific servers via `resource` parameter; "token passthrough to downstream APIs is explicitly forbidden" [64]. A gateway **must not** forward user tokens to upstream servers -- it must obtain its own.

**Automated verification:** Verify session ID is forwarded correctly. Test session expiry (send requests after server returns 404). Test DELETE cleanup. Test that the gateway does not leak session IDs across client connections. Test token isolation.

### 7. Notification Passthrough

Notifications are one-way messages without IDs; the receiver **MUST NOT** respond [63]. A gateway must:

- Forward notifications in both directions without injecting response expectations.
- Not buffer or reorder notifications relative to the request/response stream they accompany.
- On SSE streams, server-sent notifications during a request's SSE stream **SHOULD** relate to the originating request [63]. A gateway must preserve this stream-request association.
- The `notifications/initialized` message specifically must not be dropped or delayed, as it gates the transition from initialization to operation phase [66].

**Automated verification:** Send notifications through gateway, verify no response is generated. Verify `notifications/initialized` ordering is preserved. Verify server-to-client notifications arrive on the correct SSE stream.

### 8. Multiple Concurrent SSE Streams

The spec permits clients to maintain multiple simultaneous SSE connections [63]. The server **MUST** send each message on only one stream -- no broadcasting [63]. A gateway must:

- Not merge or duplicate messages across streams.
- Maintain independent stream state for resumability purposes.
- Handle the case where a POST-initiated SSE stream and a GET-initiated background stream coexist [70].

**Automated verification:** Open multiple SSE streams through gateway, verify messages are delivered to exactly one stream. Disconnect one stream, verify the other continues unaffected. Verify resumption targets the correct stream.

### 9. Existing Test Infrastructure

Two tools provide baselines for automated protocol verification:

- **MCP Inspector**: Interactive browser-based testing tool supporting both local and remote servers, multiple transports. Fixed proxy-layer issues including `Last-Event-ID` header injection (#723) and protocol version negotiation failures (#679) [71][39].
- **MCP Validator** (Janix-ai): Automated test suite covering protocol initialization, JSON-RPC message handling, batch rejection, OAuth 2.1 compliance, session security, and multi-version support (2024-11-05, 2025-03-26, 2025-06-18) [65]. Validates "secure session management with per-session protocol versions" and backward compatibility [65].

Neither tool specifically targets gateway/proxy scenarios (e.g., ID rewriting, session multiplexing, stream fan-out). This is the gap a gateway-specific test suite must fill.

---

#### From DD2: MCP Testing Tools for Gateway Validation

: How Existing MCP Testing Tools Work and Whether They Can Validate a Custom Gateway

### 1. MCP Inspector: Architecture and Capabilities

The MCP Inspector is the official testing and debugging tool maintained alongside the MCP specification by Anthropic [39]. It operates as a proxy-based architecture: a browser UI (default port 6274) communicates with a backend proxy server (default port 6277), which in turn connects to the target MCP server over one of three supported transports: stdio, SSE, or Streamable HTTP [73].

The Inspector performs real-time JSON-RPC message logging with color-coded differentiation, schema validation (flagging missing required fields or malformed responses), and interactive testing of tools, resources, prompts, and subscriptions [39]. It does **not** include a formal conformance test suite -- it is a debugging harness, not an automated validator [73].

### 2. MCP Inspector CLI Mode for CI

The Inspector supports a `--cli` flag that runs headless without the browser UI, outputting JSON to stdout [73][74]. Key CLI operations:

```bash
# List tools (JSON output)
npx @modelcontextprotocol/inspector --cli node build/index.js --method tools/list

# Call a tool with parameters
npx @modelcontextprotocol/inspector --cli node build/index.js \
  --method tools/call --tool-name mytool --tool-arg key=value

# Connect to remote SSE endpoint
npx @modelcontextprotocol/inspector --cli https://my-mcp-server.example.com

# Connect to remote Streamable HTTP with custom headers
npx @modelcontextprotocol/inspector --cli https://my-mcp-server.example.com \
  --transport http --method tools/list --header "X-API-Key: your-api-key"
```

JSON output can be piped to `jq` or assertion scripts, making it viable for CI smoke tests. However, it validates individual request/response pairs -- it does not run a systematic protocol conformance suite [74].

### 3. Pointing MCP Inspector at a Custom Gateway/Proxy

For SSE and Streamable HTTP transports, the Inspector accepts arbitrary URLs, meaning you can point it directly at a custom gateway:

```bash
# SSE transport to a gateway
npx @modelcontextprotocol/inspector --cli --transport sse \
  https://my-gateway.example.com/sse --method tools/list

# Streamable HTTP to a gateway
npx @modelcontextprotocol/inspector --cli --transport http \
  https://my-gateway.example.com/mcp --method tools/list \
  --header "Authorization: Bearer <token>"
```

The `--connect` flag and bearer token support (`--bearer-token`) enable testing gateways that require authentication [74]. URL query parameters can also configure the proxy address via `MCP_PROXY_FULL_ADDRESS` [73]. The key limitation: the Inspector trusts that it is talking to a single MCP server. It has no concept of multi-server routing or fan-out verification -- it will exercise whatever tool surface the gateway exposes but cannot verify correct upstream dispatch [39].

### 4. MCP Inspector Security Model

As of March 2025, the Inspector requires token-based authentication by default (random session token printed to console on startup), validates Origin headers against DNS rebinding, and binds to localhost only [73]. Custom tokens can be set via `MCP_PROXY_AUTH_TOKEN`, or authentication can be disabled with `DANGEROUSLY_OMIT_AUTH=true` for local development [73].

### 5. @mcp-testing/server-tester (mcp-test)

The `@mcp-testing/server-tester` package provides a Playwright-based test framework purpose-built for MCP servers [75]. Key capabilities:

- **Playwright fixtures**: First-class `mcpClient` fixture that manages connection lifecycle within standard Playwright test files
- **Dual transport**: Supports stdio (local) and HTTP (remote) connections, meaning it can target a gateway endpoint over HTTP
- **Snapshot testing**: Captures and compares deterministic responses with optional sanitizers for timestamps/IDs
- **LLM-as-a-judge**: Optional semantic evaluation of responses using OpenAI or Anthropic models
- **Built-in conformance checks**: Validates responses against MCP spec expectations
- **Matrix evals**: Runs dataset-driven test suites across multiple transports simultaneously

Initialization is via `npx mcp-test init`, which scaffolds a `playwright.config.ts`, example tests, and eval datasets [75]. Since it supports HTTP transport, pointing it at a gateway URL instead of a direct server is straightforward -- configure the transport fixture to use the gateway's HTTP endpoint. The package is experimental with evolving APIs [75].

### 6. mcp-validator (Janix-ai)

The `mcp-validator` is the most comprehensive **conformance test suite** available, providing systematic protocol compliance validation [65]. It tests across multiple protocol versions (2024-11-05, 2025-03-26, 2025-06-18) with categories including:

- **Initialization**: Version negotiation, session management
- **Tools**: Discovery, execution, schema validation, structured output (2025-06-18+)
- **Error handling**: HTTP status codes, error response format compliance
- **Batch processing**: Version-dependent request restrictions
- **Authentication**: OAuth 2.1 Bearer token validation, WWW-Authenticate headers
- **Security**: CORS validation, origin checking, DNS rebinding prevention

For HTTP servers (including gateways):
```bash
python -m mcp_testing.scripts.http_compliance_test \
  --server-url http://localhost:8088 \
  --protocol-version 2025-06-18
```

It generates JSON/HTML reports suitable for CI pipelines [65]. This is the strongest candidate for gateway validation because it exercises the protocol surface systematically rather than testing individual tool calls. If your gateway speaks Streamable HTTP, you can point `--server-url` at it and the validator treats it as any other MCP server [65].

### 7. mcpc (Apify MCP CLI)

The `mcpc` CLI client provides persistent sessions, full OAuth 2.1 support with PKCE, and a `--json` output mode for scripting [76]. Its proxy mode ("MCP proxy server for secure access to authenticated sessions from AI-generated code") is notable for gateway testing: it can maintain authenticated sessions against a gateway and relay tool calls. It supports stdio and Streamable HTTP transports, credential storage in OS keychain, and environment variable substitution for CI headless environments [76].

### 8. Other Notable Tools

- **mcpjam Inspector**: Extends testing by connecting MCP servers to actual LLMs, letting AI agents decide when to invoke tools -- useful for end-to-end gateway validation where tool descriptions must be clear enough for agent routing [77].
- **FastMCP Client**: In-memory unit testing of MCP server logic without transport, ideal for testing individual server implementations behind a gateway but not the gateway itself [78].
- **MCP Testing Framework (L-Qun)**: Multi-model evaluation framework that runs test prompts through OpenAI/Anthropic/Gemini/Deepseek against MCP servers and measures tool-call accuracy. Useful for validating that a gateway's tool descriptions produce correct model behavior across providers [79].

### 9. Strategy for Validating a Custom Gateway

Based on the available tooling, a layered approach is viable:

1. **Protocol conformance**: Run `mcp-validator` against the gateway's HTTP endpoint with `--protocol-version 2025-06-18` to verify initialization, tool listing, tool execution, error handling, and auth flows pass compliance checks [65].
2. **Functional smoke tests**: Use MCP Inspector CLI mode to list tools, call representative tools, and verify JSON responses. Script these with `jq` assertions in CI [73][74].
3. **Regression/snapshot tests**: Use `@mcp-testing/server-tester` with Playwright to capture baseline responses and detect regressions across releases [75].
4. **End-to-end agent tests**: Use mcpjam or the L-Qun framework to validate that real LLMs can discover and correctly invoke tools through the gateway [77][79].

The primary gap: no existing tool validates **gateway-specific semantics** such as correct upstream routing, multi-server aggregation, or request fan-out. All tools treat the target as an opaque MCP server. Custom test harnesses are needed for gateway routing logic.

---

---

### Subtopic 2: Security Layer Testing

#### From DD3: Phantom Token, HMAC, and Dual-Key Rotation Testing

: Testing Security Properties of Phantom Tokens, HMAC-Signed Requests, and Dual-Key Rotation

### 1. Linting for `hmac.compare_digest` Usage

Static analysis is the first line of defense against timing-vulnerable comparisons. The **precli** tool (Precaution) provides rule **PY005** (`observable_timing_discrepancy`), which performs AST-level detection of `==` operators applied to HMAC digest outputs and flags them as vulnerable [80]. The vulnerable pattern is straightforward: `digest == received_digest` must be replaced with `hmac.compare_digest(digest, received_digest)`. Suppression is available via inline comments (`# suppress: PY005` or `# suppress: observable_timing_discrepancy`) for false positives [80].

For teams needing custom enforcement, a bespoke AST visitor can walk `ast.Compare` nodes, check whether the left operand or comparators originate from `hmac.digest()` or `hmac.new().digest()` calls, and raise diagnostics when `==` or `!=` operators are used instead of `hmac.compare_digest`. This approach integrates into CI as a pre-commit hook or flake8 extension [80] [81].

**CVE-2022-48566** demonstrates why linting alone is insufficient: even `hmac.compare_digest` itself had a flaw in CPython through 3.9.1 where interpreter optimizations could short-circuit the XOR accumulation loop, breaking the constant-time guarantee [82]. Post-fix, the native C implementation ensures true constant-time behavior, but teams must enforce a minimum Python version (>= 3.9.2) as a complementary policy.

### 2. Empirically Verifying Constant-Time Comparison

Beyond linting, **measuring** timing properties is essential. Rigorous benchmarking requires: isolated CPU cores with disabled kernel RCU, hyperthreading and TurboBoost disabled, fixed CPU frequency, disabled ASLR, and the `perf` module rather than `timeit` [22]. Under these conditions:

- The `==` operator exhibits ~2.4 ns variation based on first-differing-byte position -- trivially detectable.
- A naive Python XOR-accumulation loop is **worse** than `==`, amplifying the signal ~100x due to CPython's arbitrary-precision integer operations showing data-dependent timing (~2-9 cycle variation per operation) [22].
- `hmac.compare_digest()` reduces variation to ~0.24 ns (single CPU cycle), making network-based exploitation impractical [22].

Statistical validation requires Kolmogorov-Smirnov tests to distinguish distributions, Spearman correlation across repeated runs, and Bonferroni correction for multiple comparisons [22].

The **double-HMAC strategy** provides an alternative constant-time guarantee without relying on a dedicated comparison function: both the computed and received MACs are re-HMACed with a random per-comparison key before comparison. The avalanche effect ensures that even single-byte differences produce entirely uncorrelated digests, eliminating byte-position-dependent timing [83].

### 3. Testing Phantom Token Credential Isolation

The phantom token pattern places a reverse proxy outside the agent sandbox; the agent receives only a per-session 256-bit random token that is meaningless outside `127.0.0.1:<ephemeral-port>` [84]. The proxy validates phantom tokens using constant-time comparison (e.g., the `subtle` crate's `ct_eq`) before swapping in real credentials from a system keystore [84].

**Key test scenarios for credential isolation:**

- **Direct upstream forgery**: Capture the phantom token and attempt a request directly against the upstream API (e.g., `https://api.openai.com`). Must return authentication failure, proving the token has no external value [84] [85].
- **Header injection resistance**: The proxy must strip `Authorization`, `x-api-key`, and `x-goog-api-key` headers from agent requests before injecting real credentials. Test by sending requests with pre-set authorization headers and verify they are overwritten [84].
- **Process memory inspection**: Verify real credentials do not appear in `/proc/PID/environ`, heap dumps, or `env` output within the sandbox. The architecture should use zeroizing memory (e.g., `Zeroizing<String>`) that wipes credentials on drop [84].
- **Session lifecycle revocation**: Phantom tokens expire when the session ends -- no explicit revocation API is needed. Test by saving a phantom token, terminating the session, starting a new session, and confirming the old token is rejected [84].

For production multi-agent systems, phantom tokens should additionally enforce **identity binding** (token cannot be used by a different agent identity), **scope enforcement** (read-only tokens reject write operations), and **TTL expiry** (requests after TTL return 401) [85].

### 4. Testing That HMAC Prevents Request Forgery Even With a Stolen Token

HMAC-signed request schemes bind the signature to the full canonical request: `{METHOD}\n{PATH}\n{TIMESTAMP}\n{NONCE}\n{BODY}` [21] [86]. A stolen API key alone cannot forge requests without the shared secret.

**Test matrix for HMAC request integrity:**

| Test Case | Input | Expected Result |
|---|---|---|
| Valid signature | Correct key + secret + fresh timestamp + unique nonce | 200 OK |
| Stolen key, wrong secret | Correct API key, incorrect signing secret | 401 Rejected [21] |
| Replayed request (same nonce) | Identical headers resubmitted | 401 Rejected (nonce already consumed) [21] [86] |
| Expired timestamp | Timestamp older than tolerance window (e.g., 300s) | 401 Rejected [86] |
| Tampered body | Valid signature but modified request body | 401 Rejected (signature mismatch) |
| Tampered path | Valid signature but different URL path | 401 Rejected |

**Nonce storage** must be thread-safe for production (Redis with atomic check-and-store); the in-memory `OrderedDict` approach is test-only [21] [86]. Nonces should auto-expire after the timestamp tolerance window to bound storage growth.

The verification endpoint must use `hmac.compare_digest()` for the final signature comparison -- never `==` -- to prevent an attacker with network-level timing visibility from iteratively reconstructing a valid signature [21].

### 5. Testing Dual-Key Rotation Overlap Windows

Dual-key rotation maintains concurrent validity of old and new keys during a transition window. The overlap must be long enough for consumers to migrate but short enough to limit exposure -- typically 7-30 days for API keys [87].

**Time-mocked rotation tests using `freezegun` or `time-machine`** [48]:

```python
from freezegun import freeze_time

@freeze_time("2026-03-01")
def test_both_keys_valid_during_overlap():
    old_key = rotate_key()  # creates new key, marks old for expiry at T+14d
    new_key = get_current_key()
    assert validate_request(signed_with=old_key)  # old still valid
    assert validate_request(signed_with=new_key)  # new also valid

@freeze_time("2026-03-16")
def test_old_key_rejected_after_overlap():
    assert not validate_request(signed_with=old_key)  # expired
    assert validate_request(signed_with=new_key)       # sole valid key
```

**Staged rollout testing** follows four phases: (1) create new version, (2) switch signing to new key, (3) retain verification of old key, (4) retire old key. Each phase boundary is a test checkpoint [88].

**Canary and integration testing**: Deploy rotation to a staging environment first, verify both old and new keys function, monitor for decryption/verification failure spikes, then promote to production [88]. Auth0 explicitly recommends executing signing key rotation on a development tenant first before production [89].

**Grace period for refresh token rotation** addresses concurrent-request race conditions: when multiple tabs simultaneously trigger a refresh, the first rotates the token while subsequent requests within a configurable `refreshTokenGracePeriod` receive the cached response rather than triggering false replay-attack revocation [90]. Tests must cover: concurrent refresh within the grace window (both succeed), reuse after grace period (triggers family-wide revocation), and backward compatibility at grace period = 0.

**Rollback readiness**: Maintain the ability to re-publish prior keys in JWKS or move key aliases back. Track per-key analytics to confirm zero traffic on the revoked key before closing the rotation cycle [87] [88].

---

#### From DD4: Deny-by-Default RBAC, Cerbos, and Rate Limiting Under Load

: Testing Approaches for Deny-by-Default RBAC, Cerbos Policy Evaluation, and Rate Limiting Under Concurrent Load

### 1. Cerbos Policy Test Files and `cerbos compile` for CI

Cerbos provides a built-in policy testing framework tightly coupled with its compilation step. Test files must reside in a `tests/` directory inside the policy folder and use the `_test.yaml` (or `_test.yml`, `_test.json`) suffix [24]. A test suite declares reusable `principals` (with IDs and roles), `resources` (with kind and attributes), and a `tests` array where each entry specifies `input` (principals, resources, actions) and `expected` outcomes mapping each principal-resource pair to action verdicts of `EFFECT_ALLOW` or `EFFECT_DENY` [24][91].

The critical property for deny-by-default verification: **if a principal+resource pair specified in `input` is not listed in `expected`, then `EFFECT_DENY` is expected for all actions for that pair**. Similarly, actions omitted from the `expected` block implicitly expect `EFFECT_DENY` [24]. This means a test suite that defines an `unknown` role principal and omits it from `expected` will automatically assert that the unknown role is denied all actions -- no explicit deny assertions needed. This is a powerful pattern for proving deny-by-default semantics hold.

Example test structure:

```yaml
name: ContactPolicyTests
principals:
  admin:
    id: adminID
    roles: [admin]
  user:
    id: userID
    roles: [user]
  unknown:
    id: unknownID
    roles: [visitor]
resources:
  contact:
    id: contact1
    kind: contact
tests:
  - name: role-based access
    input:
      principals: [admin, user, unknown]
      resources: [contact]
      actions: [create, read, update, delete]
    expected:
      - principal: admin
        resource: contact
        actions:
          create: EFFECT_ALLOW
          read: EFFECT_ALLOW
          update: EFFECT_ALLOW
          delete: EFFECT_ALLOW
      - principal: user
        resource: contact
        actions:
          create: EFFECT_ALLOW
          read: EFFECT_ALLOW
          update: EFFECT_ALLOW
          delete: EFFECT_DENY
      # 'unknown' principal omitted => all actions EFFECT_DENY
```

For CI integration, `cerbos compile` validates policies **locally without a running PDP**, making it suitable for pre-merge checks [24][92]. CI examples include:

- **GitHub Actions**: `cerbos/cerbos-compile-action@v1` with a `policyDir` parameter [24]
- **Docker**: `docker run --rm -v $(pwd):/policies ghcr.io/cerbos/cerbos:latest compile /policies` [92]
- **Dagger**: `dagger -m github.com/cerbos/dagger-cerbos call compile --policy-dir=./cerbos` [24]

Test filtering via `--test-filter` supports selective execution by suite, principal, resource, or action using glob patterns [24].

Additionally, Cerbos enforces **DENY precedence**: if more than one rule matches a given input, a rule specifying `EFFECT_DENY` takes precedence over `EFFECT_ALLOW` [93]. This is architecturally important -- the authorization engine itself is deny-biased, not just the test framework.

### 2. Testing Deny-by-Default When Cerbos Is Unreachable

The Cerbos Python SDK (available via PyPI as `cerbos`) provides both sync (`CerbosClient`) and async (`AsyncCerbosClient`) gRPC clients [94]. The SDK includes built-in gRPC service config for retry policies and backoffs, configurable via `channel_options` [94]. However, the SDK **does not document an explicit deny-by-default fallback when the PDP is unreachable** [94].

This means the application layer must implement the fail-closed pattern itself. The recommended testing approach:

1. **Use TestContainers** (`cerbos[testcontainers]` extra) to spin up a real PDP in tests, then stop the container mid-test to simulate unreachability [94].
2. **Assert that gRPC connection errors propagate as exceptions** (not silent allow decisions).
3. **Wrap the SDK call in application code** with a try/except that returns deny on any connection error, and test that wrapper.

```python
# Application-level fail-closed wrapper
async def check_permission(client, principal, resource, action):
    try:
        return await client.is_allowed(action, principal, resource)
    except Exception:
        return False  # deny-by-default on PDP failure
```

Testing this wrapper with a deliberately unreachable PDP address confirms the fail-closed guarantee at the integration level.

### 3. Load Testing Rate Limiters with asyncio.gather

Several libraries enable Redis-backed async rate limiting suitable for concurrent load tests:

**asyncio-redis-rate-limit** uses a `RateSpec(requests=N, seconds=T)` configuration and provides both decorator and context-manager patterns for async functions. It claims to be "free of race-conditions" and works across distributed processes via Redis [95].

**self-limiters** implements both semaphore (concurrent request cap) and token bucket (requests per interval) algorithms using Redis Lua scripts for atomic execution. Redis's single-threaded Lua execution provides FIFO ordering "out of the box" without distributed locks [96]. Benchmark testing shows ~0.6ms overhead per semaphore call at 100 concurrent tasks.

For load testing a rate limiter, the `asyncio.gather` pattern is the standard approach:

```python
import asyncio
import time

async def test_rate_limiter_concurrent_burst():
    """Verify rate limiter rejects excess requests under concurrent load."""
    limiter = RedisRateLimiter(max_requests=10, window_seconds=1, redis=redis_client)
    
    async def attempt_request(key: str) -> bool:
        try:
            async with limiter(key):
                return True
        except RateLimitExceeded:
            return False
    
    # Fire 50 concurrent requests
    results = await asyncio.gather(
        *[attempt_request("user:123") for _ in range(50)]
    )
    
    allowed = sum(1 for r in results if r)
    denied = sum(1 for r in results if not r)
    assert allowed <= 10, f"Rate limiter allowed {allowed} > 10 requests"
    assert denied >= 40
```

Key testing patterns for rate limiters under load [97][96]:

- **Burst testing**: Fire N >> limit concurrent requests with `asyncio.gather`, assert that exactly `limit` are allowed.
- **Window reset testing**: Exhaust quota, wait for window expiration, confirm requests succeed again.
- **Sliding window boundary testing**: Send requests straddling two windows to verify sliding (not fixed) window behavior.
- **Distributed testing**: Run multiple async processes against the same Redis key to verify cross-process enforcement.

The **sliding window** algorithm using Redis sorted sets tracks individual request timestamps as scores, pruning entries outside the rolling window [98]. This is more accurate than fixed windows but requires atomic multi-command execution via `PIPELINE` or Lua scripts.

For test infrastructure, **FakeRedis** provides a pure-Python Redis implementation that eliminates the need for a real Redis server in unit tests [52], while **pytest-mock-resources** can provision a shared Redis Docker container for integration tests.

### 4. Testing Dual-Layer RBAC: Discovery Filtering + Call Guard

The dual-layer RBAC pattern enforces authorization at two points: (1) **discovery/list filtering** that constrains which resources a user can see, and (2) **call-level guards** that enforce permissions on individual resource access [99]. This is a defense-in-depth strategy -- the frontend adapts UI based on roles for usability, but "RBAC policies must be enforced at the backend (API) to guarantee security and consistency" [99].

Testing this dual-layer model requires verifying both layers independently and in combination:

**Layer 1 -- Discovery filtering tests:**
- Assert that list/search endpoints return only resources the principal is authorized to discover.
- Test with principals of different roles: an admin sees all resources, a viewer sees only public ones, an unknown role sees none.
- Verify that resources created after role assignment appear correctly in filtered results.

**Layer 2 -- Call-level guard tests:**
- For each resource returned by discovery, verify that the principal can perform allowed actions and is denied forbidden ones.
- Test direct resource access by ID (bypassing discovery) to confirm the guard rejects unauthorized access even if a user guesses a resource ID.

**Combined integration tests:**
- Verify that no resource returned by discovery is denied at the call level (consistency between layers).
- Verify that resources NOT returned by discovery are also denied at the call level (no bypass via direct access).

The ARBITER research framework [100] demonstrates this dual-layer pattern in RAG systems: an **input filter** validates queries against role-based permissions before retrieval, and an **output filter** blocks unauthorized content in generated responses. Testing showed the combined approach achieved F1-scores of 0.83-0.89, compared to 0.32-0.43 without either layer -- confirming that **dual-layer enforcement is substantially more robust than single-layer** [100].

Envoy's RBAC filter provides an infrastructure-level analog: **shadow mode** allows new RBAC policies to be tested against live traffic without enforcement, logging violations for analysis before switching to enforcement mode [101]. This pre-production validation pattern is directly applicable: deploy new dual-layer policies in shadow/audit mode, verify no legitimate requests would be blocked, then activate enforcement.

The Datadog guardrails framework [102] recommends **trace-based testing** for multi-layer enforcement: instrument each authorization checkpoint, then query traces to verify that (a) both layers evaluated every request, (b) deny decisions at either layer blocked the request, and (c) no request bypassed a layer entirely. This observability-driven testing approach catches enforcement gaps that unit tests alone might miss.

A practical test structure for dual-layer RBAC:

```python
@pytest.mark.parametrize("role,visible_count,can_delete", [
    ("admin", 10, True),
    ("viewer", 5, False),   # sees only public resources
    ("anonymous", 0, False), # sees nothing
])
async def test_dual_layer_enforcement(role, visible_count, can_delete):
    principal = make_principal(role=role)
    
    # Layer 1: discovery filtering
    discovered = await list_resources(principal)
    assert len(discovered) == visible_count
    
    # Layer 2: call-level guard on each discovered resource
    for resource in discovered:
        assert await check_access(principal, resource, "read") is True
        assert await check_access(principal, resource, "delete") is can_delete
    
    # Layer 2: direct access bypass attempt
    secret_resource = get_resource_by_id("admin-only-resource-id")
    if role != "admin":
        assert await check_access(principal, secret_resource, "read") is False
```

### 5. Centralizing Authorization for Testability

A recurring theme across sources is that centralizing policy logic into a dedicated service (like Cerbos PDP) makes RBAC **unit-testable in isolation** [99]. Rather than scattering `if user.role == "admin"` checks across microservices, a single policy engine can be tested with `cerbos compile`, and the application code only needs integration tests confirming it calls the engine and respects its decisions. Anti-pattern: hand-rolled authorization scattered across services creates "inconsistency, poor auditability, and unmaintainable edge cases" [99].

---

---

### Subtopic 3: Integration and End-to-End Testing

#### From DD5: Stub MCP Server Test Harness

: Building a Test Harness with Stub MCP Servers for Gateway Integration Testing

### 1. In-Memory Testing with FastMCP Client (The Foundation)

The core pattern for stub MCP server testing avoids subprocess overhead entirely. FastMCP's `Client` accepts a `FastMCP` server instance directly as its transport target, routing JSON-RPC messages in-process through the real stdio serialization path [2]. This means your test fixture creates a `FastMCP` object, registers known tools on it, and hands it to `Client`---no port allocation, no process lifecycle, no flaky network:

```python
import pytest
from fastmcp import FastMCP, Client

@pytest.fixture
def stub_server():
    server = FastMCP("StubUpstream")

    @server.tool()
    def echo(text: str) -> str:
        return f"echo:{text}"

    @server.tool()
    def add(a: int, b: int) -> int:
        return a + b

    return server

async def test_tool_discovery(stub_server: FastMCP):
    async with Client(stub_server) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert names == {"echo", "add"}

async def test_call_tool(stub_server: FastMCP):
    async with Client(stub_server) as client:
        result = await client.call_tool("add", {"a": 3, "b": 7})
        assert result.content[0].text == "10"
```

Critical detail: instantiate the `Client` context manager **inside** each test function, not as a separate fixture. Wrapping `Client` in a fixture causes event loop conflicts with `pytest-asyncio` [3]. Configure `asyncio_mode = "auto"` in `pyproject.toml` to avoid decorating every test with `@pytest.mark.asyncio`.

### 2. Testing Actual HTTP/SSE Transport with `run_server_in_process` and `run_server_async`

When you need to verify real Streamable HTTP behavior (e.g., header propagation, `Mcp-Session-Id` tracking, SSE reconnection with `Last-Event-ID`), FastMCP provides two utilities [103]:

**In-process async server** (preferred for speed, debuggable):
```python
from fastmcp import FastMCP, Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.utilities.tests import run_server_async

def create_stub() -> FastMCP:
    server = FastMCP("HTTPStub")
    @server.tool()
    def greet(name: str) -> str:
        return f"Hello, {name}!"
    return server

@pytest.fixture
async def http_url():
    server = create_stub()
    async with run_server_async(server) as url:
        yield url

async def test_http_transport(http_url: str):
    async with Client(transport=StreamableHttpTransport(http_url)) as client:
        assert await client.ping() is True
        result = await client.call_tool("greet", {"name": "Gateway"})
        assert result.data == "Hello, Gateway!"
```

**Subprocess isolation** (for testing process boundary, env var injection):
```python
from fastmcp.utilities.tests import run_server_in_process

def run_server(host: str, port: int) -> None:
    server = FastMCP("SubprocessStub")
    @server.tool
    def version() -> str:
        return "1.0.0"
    server.run(host=host, port=port)

@pytest.fixture
async def subprocess_url():
    with run_server_in_process(run_server, transport="http") as url:
        yield f"{url}/mcp"
```

`run_server_in_process` handles port allocation, startup waiting, and cleanup automatically [103]. Use this only when subprocess isolation is genuinely needed---in-process is 10-100x faster.

### 3. Testing stdio Subprocess Communication

For gateway scenarios where you proxy to an upstream stdio server (like `npx -y @notionhq/notion-mcp-server`), the `Client` natively handles subprocess management:

```python
async def test_stdio_upstream():
    # Client launches subprocess, communicates via stdin/stdout JSON-RPC
    async with Client("python my_stdio_server.py") as client:
        tools = await client.list_tools()
        assert len(tools) > 0
```

For lower-level control (e.g., testing raw JSON-RPC framing over stdio), the Testcontainers pattern demonstrates direct socket communication with Docker containers running stdio MCP servers [104]:

```python
def encode_mcp_message(payload: dict) -> bytes:
    return (json.dumps(payload) + "\n").encode("utf-8")

# Attach to container stdin/stdout, send raw JSON-RPC
raw_socket.sendall(encode_mcp_message({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-11-25", "capabilities": {},
               "clientInfo": {"name": "pytest", "version": "0.1"}}
}))
response = read_mcp_message(raw_socket, timeout=20)
assert "result" in response
assert "serverInfo" in response["result"]
```

### 4. Stub Server Design for Gateway Integration Tests

For CommandClaw's aggregator pattern (multiple upstream servers mounted with namespace prefixing via `FastMCPProxy`), build a multi-server fixture that mirrors real config:

```python
from commandclaw_mcp.config import Settings, ServerConfig, GatewayConfig

def make_stub_server(tools: dict[str, callable]) -> FastMCP:
    server = FastMCP("Stub")
    for name, fn in tools.items():
        server.tool()(fn)
    return server

@pytest.fixture
async def gateway_with_stubs():
    """Two stub upstreams behind the gateway aggregator."""
    weather_stub = make_stub_server({
        "get_forecast": lambda city: f"Sunny in {city}",
    })
    github_stub = make_stub_server({
        "list_repos": lambda user: [f"{user}/repo1"],
    })

    # Start both as HTTP servers for realistic transport testing
    async with run_server_async(weather_stub) as weather_url, \
               run_server_async(github_stub) as github_url:

        settings = Settings(
            gateway=GatewayConfig(port=0),  # random port
            servers={
                "weather": ServerConfig(url=weather_url),
                "github": ServerConfig(url=github_url),
            },
        )
        # Build the actual gateway under test
        from commandclaw_mcp.gateway.aggregator import create_gateway_mcp
        gateway = create_gateway_mcp(settings)

        async with Client(gateway) as client:
            yield client
```

This validates the full path: gateway `mount()` -> namespace prefixing -> `FastMCPProxy` -> upstream HTTP -> stub tool execution. Assertions become predictable because the stub tools return deterministic values:

```python
async def test_namespace_prefixed_tools(gateway_with_stubs):
    client = gateway_with_stubs
    tools = await client.list_tools()
    names = {t.name for t in tools}
    assert "weather_get_forecast" in names
    assert "github_list_repos" in names

    result = await client.call_tool("weather_get_forecast", {"city": "Portland"})
    assert "Sunny in Portland" in result.content[0].text
```

### 5. SSE Streaming Response Testing

For SSE-specific validation (e.g., verifying `Last-Event-ID` resumability or streaming progress), use `httpx` with SSE support against a stub server running via `run_server_async`:

```python
import httpx

async def test_sse_streaming(http_url: str):
    async with httpx.AsyncClient() as http:
        async with http.stream("GET", f"{http_url}/sse") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    event = json.loads(line[5:])
                    # Validate JSON-RPC response structure
                    assert "jsonrpc" in event
                    break
```

The `SessionTrackingMiddleware` in CommandClaw's aggregator tracks `Mcp-Session-Id` and `Last-Event-ID` headers---test these by making sequential requests and asserting header propagation [105].

### 6. Recording and Replay for CI Determinism

`mcp-recorder` provides a VCR-like cassette approach for MCP: record live interactions, commit cassettes, replay in CI without network or credentials [106]:

```python
@pytest.mark.mcp_cassette("cassettes/weather_flow.json")
async def test_weather_flow(mcp_replay_url):
    async with Client(mcp_replay_url) as client:
        result = await client.call_tool("get_forecast", {"city": "NYC"})
        assert "sunny" in result.content[0].text.lower()
```

Recording supports both HTTP (`--mcp-target http://...`) and stdio (`--mcp-target-stdio "python server.py"`) modes. Cassettes support configurable matching strategies (method+params, sequential, strict) and credential redaction (`--redact-env API_KEY`) [106].

### 7. Mocking External Dependencies Inside Tools

When stub tools need to simulate external APIs (databases, HTTP services), use `unittest.mock.AsyncMock` or `respx` (already in CommandClaw's dev dependencies):

```python
import respx
from httpx import Response

@respx.mock
async def test_tool_with_external_api(stub_server):
    respx.get("https://api.weather.com/NYC").mock(
        return_value=Response(200, json={"temp": 72})
    )
    async with Client(stub_server) as client:
        result = await client.call_tool("fetch_weather", {"city": "NYC"})
        assert "72" in result.content[0].text
```

### 8. Test Configuration Patterns

Use shorter timeouts in tests to fail fast [105]:

```python
TEST_CONFIG = {
    "connection_timeout": 5.0,   # vs 30s production
    "invocation_timeout": 10.0,  # vs 120s production
    "max_retries": 2,            # vs 5 production
}
```

For Testcontainers-based integration tests where you spin up real Docker containers (Redis, Cerbos, upstream MCP servers), use session-scoped fixtures with health-check polling rather than arbitrary `time.sleep()` [104][107]:

```python
@pytest.fixture(scope="session")
def upstream_container():
    with DockerContainer("my-mcp-server:latest").with_kwargs(
        stdin_open=True, tty=False
    ) as container:
        wait_for_logs(container, "MCP server started", timeout=60)
        yield container
```

---

#### From DD6: Docker Compose Test Environments

: Docker Compose Test Environments for Gateway Testing with Redis, Cerbos PDP, and Upstream MCP Servers

### Testcontainers-Python for Redis

[110] The `testcontainers[redis]` Python package provides a `RedisContainer` class that manages Redis lifecycle within pytest. Basic usage follows a context-manager pattern: `with RedisContainer() as redis_container: client = redis_container.get_client()`. The container auto-assigns random free ports to avoid collisions, retrievable via `get_container_host_ip()` and `get_exposed_port()`.

[111] For async gateway code using `redis.asyncio`, the official `RedisContainer` was extended with async support (merged via PR #434). The pattern subclasses `RedisContainer` to add `get_async_client(**kwargs)` returning an `await`-able `Redis` instance configured with the container's dynamic host/port. This is critical for testing async gateway middleware that uses Redis for session state or rate limiting.

[112] Testcontainers-python currently lacks a built-in `wait_for_healthcheck()` method (issue #241 remains open). The workaround polls the underlying Docker container's health state in a loop: `container.get_wrapped_container().reload(); if underlying_container.health == 'healthy': break`, with a configurable timeout. This matters when composing multiple containers (Redis + Cerbos + upstream) that must all be healthy before gateway tests begin.

### Testcontainers-Python for Cerbos PDP

[94] The Cerbos Python SDK ships its own testcontainers integration via the `cerbos[testcontainers]` extra. The `CerbosContainer` class from `cerbos.sdk.container` handles the full PDP lifecycle: instantiate, mount policy files via `with_volume_mapping(policy_dir, "/policies")`, start the container, call `container.wait_until_ready()`, then retrieve the HTTP endpoint with `container.http_host()`. This gives each test suite an isolated PDP instance loaded with the exact policies under test.

[113] Cerbos PDP exposes port 3592 (HTTP/REST) and 3593 (gRPC). The built-in `cerbos healthcheck` CLI command supports both `--kind=grpc` (default) and `--kind=http` modes. For Docker Compose deployments, the healthcheck stanza is: `test: ["CMD", "cerbos", "healthcheck", "--config=...", "--kind=http", "--insecure"]` with configurable `interval`, `timeout`, and `retries`. The gRPC check uses the standard gRPC health protocol and is recommended since the HTTP layer depends on gRPC internally.

### Docker Compose Test Profiles

[114] The `pytest-docker` plugin (avast/pytest-docker) provides session-scoped fixtures that call `docker compose up` with the `--wait` flag, which respects both image-level `HEALTHCHECK` instructions and compose-level `healthcheck` stanzas. The `docker_services.wait_until_responsive(timeout=30.0, pause=0.1, check=lambda: is_responsive(url))` method allows custom readiness probes beyond Docker's built-in health checks -- useful for verifying that a gateway's `/health` endpoint returns 200 after all upstreams connect.

[115] The `pytest-docker-compose` plugin offers scoped fixtures (`function_scoped_container_getter`, `session_scoped_container_getter`, etc.) that return `NetworkInfo` objects with `hostname`, `host_port`, and `container_port`. Multiple compose files can be specified via `--docker-compose=base.yml,test-overrides.yml`, enabling test profiles that layer gateway, Redis, Cerbos, and mock MCP server definitions. The `--use-running-containers` flag supports pre-warmed environments for faster local iteration.

[116] Docker Compose v5.0 (December 2025) introduced separate `start_interval` and `interval` healthcheck parameters, allowing rapid polling during startup (e.g., 2s) that transitions to economical monitoring (e.g., 30s) once healthy. A gateway test profile typically chains `depends_on` conditions: the gateway service depends on Redis (`condition: service_healthy`), Cerbos PDP (`condition: service_healthy`), and upstream MCP stubs (`condition: service_healthy`), ensuring the full dependency graph is ready before the test runner starts.

### Compose-Based Gateway Test Environments

[117] A representative Docker Compose test environment for a gateway proxy includes: (a) a Redis service with `healthcheck: test: ["CMD", "redis-cli", "ping"]`; (b) a Cerbos PDP service with policy volumes and `healthcheck: test: ["CMD", "cerbos", "healthcheck"]`; (c) one or more upstream MCP server stubs; and (d) the gateway under test, which `depends_on` all three with `condition: service_healthy`. The test runner (pytest) connects to the gateway's exposed port and exercises authorization, caching, and proxying paths end-to-end.

[118] The Docker MCP Gateway (`docker/mcp-gateway`) provides a reference architecture for proxying upstream MCP servers. Its compose configuration mounts `/var/run/docker.sock` so the gateway can dynamically spawn MCP server containers. Port 8811 serves the stdio-to-HTTP bridge. For testing, this pattern can be adapted: define upstream MCP server stubs as compose services, point the gateway at them via environment configuration, and run integration tests against the gateway's unified endpoint.

[119] Microsoft's MCP Gateway implements session-aware stateful routing with adapter-based management APIs (`POST /adapters`, `GET /tools/{name}/status`). It uses StatefulSets in Kubernetes but can run locally via Docker with port-forwarding. The health check pattern queries `/tools/{name}/status` for each registered adapter, providing a model for gateway health probes that verify not just the proxy process but also connectivity to all upstream MCP servers.

### Testcontainers vs Docker Compose Trade-offs

[120] Testcontainers excels when tests need programmatic container control (dynamic port discovery, per-test isolation, no external scripts). Docker Compose excels when the environment is complex (many interdependent services with ordered startup) and the configuration should be reusable across local dev, CI, and staging. For gateway testing with Redis + Cerbos + MCP upstreams, a hybrid approach is common: Docker Compose defines the multi-service topology with health checks, while pytest-docker or pytest-docker-compose manages the lifecycle and injects connection details as fixtures.

[121] Best practices for health-check waiting in containerized test environments include: (a) verify actual application functionality, not just process existence; (b) use `depends_on` with `condition: service_healthy` rather than `wait-for-it.sh` scripts; (c) set resource limits (`shm_size`, memory) to prevent OOM in CI; (d) use custom Docker networks for test isolation; and (e) mount volumes for coverage reports and test artifacts.

---

---

### Summary

The Deeper Dive research extends the General Understanding findings across three domains. For **protocol compliance**, the 2025-06-18 MCP specification introduces breaking changes (batch request removal, mandatory `MCP-Protocol-Version` header) and tightens SSE resumability semantics (globally unique event IDs, per-stream replay only, `Last-Event-ID` mandatory on reconnect) [63][68]. The MCP Validator (Janix-ai) provides the most comprehensive automated conformance suite [65], but no existing tool validates gateway-specific semantics such as message ID rewriting, session multiplexing, or stream fan-out. For **security testing**, precli PY005 and custom AST visitors enforce `hmac.compare_digest` usage at lint time [81], while CVE-2022-48566 demonstrates that the function itself had a constant-time flaw in early Python 3.9 [83]. The phantom token pattern isolates credentials from agent sandboxes [85]; testing requires proving tokens have no external value, headers are stripped before credential injection, and credentials never appear in process memory. Cerbos policy tests implicitly assert deny-by-default when principals are omitted from expected outcomes [24], and the application layer must implement fail-closed wrappers since the SDK does not default to deny on PDP unreachability [95]. For **integration testing**, FastMCP's `Client(server)` and `run_server_async` provide the fastest feedback loop for stub-based gateway tests [2][104], while testcontainers-python (with `cerbos[testcontainers]` and `RedisContainer`) enables programmatic container lifecycle per-test [95][111]. Docker Compose with `depends_on: condition: service_healthy` chains provide the most realistic multi-service environments [118], and the pytest-docker plugin bridges Compose lifecycle into pytest fixtures [116].
