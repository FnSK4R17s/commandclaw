# Testing Strategies for MCP Gateway Proxies

**Author:** Background Research Agent (BEARY)
**Date:** 2026-03-28

---

## Abstract

An MCP gateway proxy sits between AI agent clients and upstream MCP servers, adding security enforcement (HMAC verification, phantom token exchange, RBAC), session management, rate limiting, and multi-server aggregation. Testing such a gateway differs fundamentally from testing a standard REST API: the gateway must preserve MCP protocol invariants (JSON-RPC message ID correlation, capability negotiation, SSE resumability, notification passthrough) while interposing its own middleware. This whitepaper synthesizes testing patterns from the MCP Python SDK, FastMCP, mcp-proxy, Cerbos, and the broader Python async testing ecosystem into a concrete test architecture for CommandClaw-MCP. It covers protocol compliance verification, security layer testing, RBAC and rate limiting under concurrent load, session and state management, integration testing with stub MCP servers and Docker Compose environments, and the current MCP testing tools landscape.

## 1. Introduction: Why Testing an MCP Gateway Is Different

A conventional API proxy forwards HTTP requests and responses. An MCP gateway proxy must additionally preserve a stateful, bidirectional JSON-RPC 2.0 protocol with session semantics, capability negotiation, and streaming transport modes. Three properties make this harder to test than standard API middleware.

First, **protocol statefulness**. The MCP lifecycle begins with a three-phase initialization handshake (`initialize` request, `initialize` response, `notifications/initialized` notification) that gates all subsequent operations [66]. A gateway that interposes on this handshake must either transparently forward it or perform split negotiation with each side independently. Either approach must be tested to ensure the gateway does not violate ordering constraints -- the spec forbids non-ping requests before initialization completes [66].

Second, **bidirectional streaming**. The Streamable HTTP transport supports server-sent events (SSE) with resumability via `Last-Event-ID` [63][33]. A gateway that terminates SSE on the client side and maintains its own upstream connections must implement event ID tracking, per-stream replay buffers, and correct routing of server-initiated notifications. Each of these is a source of subtle bugs -- the MCP Inspector itself had a bug where `Last-Event-ID` was not sent on reconnect (#723) [71].

Third, **multi-layer security interposition**. The gateway adds HMAC signature verification, phantom token exchange, RBAC enforcement via Cerbos, and rate limiting -- all as middleware that runs before MCP message dispatch. Each layer can reject requests, and the composition of layers must preserve deny-by-default semantics even when individual components fail (e.g., Cerbos PDP unreachable). Testing the security stack requires verifying both individual layer correctness and the composed behavior under adversarial conditions.

The rest of this paper presents concrete patterns for each testing domain, with code examples targeting Python 3.12+, pytest, FastMCP, and the official MCP Python SDK.

## 2. MCP Protocol Compliance Testing

### 2.1 In-Memory Transport as the Core Testing Primitive

The official MCP Python SDK provides `create_connected_server_and_client_session()` from `mcp.shared.memory`, which creates a directly-connected `Server`/`ClientSession` pair via in-memory anyio object streams [31][8]. FastMCP wraps this further: passing a `FastMCP` server instance directly to `Client(mcp_server)` establishes an in-process transport that uses the real MCP protocol internally with zero network overhead [2][3]:

```python
from fastmcp import FastMCP, Client

mcp = FastMCP("TestServer")

@mcp.tool()
def add(a: int, b: int) -> int:
    return a + b

async def test_tool_round_trip():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        assert any(t.name == "add" for t in tools)
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert result[0].text == "3"
```

Critical implementation detail: instantiate `Client` inside each test function, not as a pytest fixture. Pytest's async fixtures and test functions may run in different event loops, causing task cancellation errors [3].

### 2.2 Proxy Parity Testing

The most reusable gateway testing pattern comes from `sparfenyuk/mcp-proxy`. Their `test_proxy_server.py` uses parametrized session generators to run identical assertions against both direct and proxied connections [4]:

```python
@pytest.fixture(params=["server", "proxy"])
def session_generator(request) -> SessionContextManager:
    if request.param == "server":
        return in_memory  # direct via create_connected_server_and_client_session
    return proxy           # wraps server in proxy, connects via in_memory again

async def test_list_tools(session_generator, server):
    async with session_generator(server) as session:
        result = await session.list_tools()
        assert len(result.tools) > 0
```

This guarantees behavioral parity: every test runs against both the raw server and the gateway, catching any behavioral divergence introduced by the proxy layer. The mcp-proxy suite covers tool calls, resource listing, prompt rendering, subscription lifecycle, progress notifications, and completions [4].

### 2.3 Capability-Gated Negative Testing

A gateway must correctly propagate capability restrictions. When an upstream server does not register tools, the gateway must not advertise tool capability to the client. mcp-proxy tests verify this by asserting `not result.capabilities.tools` when only prompts are registered, then confirming `pytest.raises(McpError, match="Method not found")` when the client calls `list_tools()` [4][5].

### 2.4 Message ID Preservation

The MCP specification mandates that request IDs are strings or integers (never `null`), unique within a session, and preserved exactly in responses [63]. A gateway that multiplexes upstream connections by rewriting IDs must maintain a bijective mapping and restore original IDs on the return path. Notifications must never carry IDs [63].

Test by injecting requests with known IDs (integer, string, large numeric values near JSON precision limits) through the gateway and asserting exact ID match on responses. The SDK's `StreamSpyCollection` intercepts raw JSON-RPC messages at the protocol level, enabling ID verification without parsing higher-level response objects [8].

### 2.5 Conformance Suites: mcp-validator

The `mcp-validator` (Janix-ai) is the most comprehensive automated conformance test suite available [65]. It tests across protocol versions (2024-11-05, 2025-03-26, 2025-06-18) and covers initialization, tool discovery/execution, error handling, batch rejection (2025-06-18 removes batch support [64]), OAuth 2.1, CORS, and DNS rebinding prevention. For HTTP servers including gateways:

```bash
python -m mcp_testing.scripts.http_compliance_test \
  --server-url http://localhost:8088 \
  --protocol-version 2025-06-18
```

It generates JSON/HTML reports suitable for CI [65]. The primary gap: it treats the target as an opaque MCP server and cannot validate gateway-specific semantics (upstream routing, multi-server aggregation, ID rewriting).

### 2.6 SSE Resumability Testing

The Streamable HTTP transport's resumability mechanism requires [63][69][70]:

- Server-assigned event IDs that are globally unique within a session
- Client sending `Last-Event-ID` on reconnection
- Server replaying missed events only from the disconnected stream -- never cross-stream replay
- Recommended event ID encoding: `${streamId}/${eventNumber}` for correct routing [70]

A gateway that terminates SSE client-side must implement its own event store. Test by establishing an SSE stream through the gateway, injecting events with IDs, simulating disconnect, reconnecting with `Last-Event-ID`, and verifying only the correct stream's events are replayed. Open multiple concurrent SSE streams to verify no message duplication across streams [63].

### 2.7 Protocol Version Header Enforcement

The 2025-06-18 spec requires all HTTP requests to include `MCP-Protocol-Version: <negotiated-version>` [68]. Servers must respond `400 Bad Request` to invalid versions. Test that the gateway preserves this header on forwarded requests and correctly rejects requests with missing or invalid versions.

## 3. Security Layer Testing

### 3.1 HMAC Verification

HMAC middleware testing covers four axes [21]:

**Canonical string construction**: The canonical form is typically `METHOD\nPATH\nSORTED_QUERY\nTIMESTAMP\nNONCE\nBODY_HASH`. Test with empty body, query params with special characters, and trailing slashes [21].

**Timestamp tolerance**: Use `freezegun` or `time-machine` to test boundary conditions. With a 300-second window: `now - 301` (reject), `now - 300` (accept), `now + 300` (accept), `now + 301` (reject) [21]. Always use `real_asyncio=True` with freezegun in async tests to avoid breaking the event loop [48].

**Nonce replay prevention**:

```python
def test_replay_attack_prevented():
    nonce = str(uuid.uuid4())
    headers = build_hmac_headers(nonce=nonce, timestamp=now_iso())
    response1 = client.post("/secure", headers=headers, content=b'{"x":1}')
    assert response1.status_code == 200
    response2 = client.post("/secure", headers=headers, content=b'{"x":1}')
    assert response2.status_code == 401
```

Nonce storage must be thread-safe (Redis with atomic check-and-store in production; `OrderedDict` with TTL expiry in tests) [21][87].

**Constant-time comparison linting**: Use `hmac.compare_digest()` exclusively. Naive Python XOR-accumulation loops are worse than `==` due to CPython's data-dependent arbitrary-precision integer operations [22]. The `precli` tool provides rule PY005 for AST-level detection of `==` on HMAC digests [81][23]. CVE-2022-48566 demonstrates that even `hmac.compare_digest` itself had a timing flaw in CPython through 3.9.1 [83] -- enforce a minimum Python version >= 3.9.2.

The double-HMAC strategy provides an alternative: re-HMAC both the computed and received MACs with a random per-comparison key before comparing. The avalanche effect eliminates byte-position-dependent timing [84].

### 3.2 Phantom Token Credential Isolation

The phantom token pattern places a reverse proxy outside the agent sandbox; the agent receives only a per-session 256-bit random token meaningless outside `127.0.0.1:<ephemeral-port>` [85]. The proxy validates phantom tokens using constant-time comparison before swapping in real credentials from a system keystore.

Test scenarios for credential isolation [85][86]:

| Test Case | Verification |
|---|---|
| Direct upstream forgery | Use phantom token against `https://api.openai.com` directly -- must fail |
| Header injection resistance | Send request with pre-set `Authorization` header -- proxy must overwrite |
| Process memory inspection | Real credentials must not appear in `/proc/PID/environ` or heap dumps |
| Session lifecycle revocation | Save token, terminate session, start new session -- old token rejected |
| Identity binding | Token from agent A rejected when used by agent B |
| Scope enforcement | Read-only token rejects write operations |

### 3.3 Dual-Key Rotation with Time Mocking

Dual-key rotation maintains concurrent validity of old and new keys during a transition window (typically 7-30 days) [88]. Test with `freezegun` [48]:

```python
from freezegun import freeze_time

@freeze_time("2026-03-01")
def test_both_keys_valid_during_overlap():
    old_key = rotate_key()   # creates new key, marks old for expiry at T+14d
    new_key = get_current_key()
    assert validate_request(signed_with=old_key)   # old still valid
    assert validate_request(signed_with=new_key)    # new also valid

@freeze_time("2026-03-16")
def test_old_key_rejected_after_overlap():
    assert not validate_request(signed_with=old_key)  # expired
    assert validate_request(signed_with=new_key)       # sole valid key
```

For `MultiFernet` key rotation, `MultiFernet.rotate(token)` re-encrypts under the primary key while preserving the original timestamp. Verify with `decrypt_at_time()` [45]. Test the retirement workflow: build `MultiFernet([key3, key1, key2])`, rotate all tokens, drop key1/key2, assert old tokens fail [45][47].

### 3.4 Credential Encryption Round-Trips

Test Fernet encrypt/decrypt with `decrypt(encrypt(plaintext)) == plaintext`. Test `InvalidToken` for tampered ciphertext, wrong key, and expired TTL. Use `decrypt_at_time(token, ttl, current_time)` for deterministic TTL testing without time-mocking [45].

For Argon2id KDF, use production-strength parameters (`time_cost=3`, `memory_cost=65536`) in a small number of `@pytest.mark.slow` integration tests, and drastically reduced parameters (`time_cost=1`, `memory_cost=64`) in unit tests [46].

### 3.5 Memory Zeroing

Python's immutable strings prevent reliable memory zeroing. Store credentials in `bytearray` or `ctypes.create_string_buffer()`, then zero with `ctypes.memset()`. Verify by inspecting memory with `ctypes.string_at(address, length)` and asserting all bytes are `\x00` [60]:

```python
def test_credential_zeroing():
    buf = ctypes.create_string_buffer(b"supersecret")
    addr = ctypes.addressof(buf)
    ctypes.memset(addr, 0, len(buf))
    assert ctypes.string_at(addr, len(buf)) == b"\x00" * len(buf)
```

Caveat: the CPython GC may have copied the secret elsewhere (string interning, internal buffers). The `pyca/cryptography` team closed the secure-wipe feature request after 8 years, noting OS-level memory swapping further undermines the guarantee [62]. Document this limitation in the threat model.

## 4. RBAC and Rate Limiting

### 4.1 Cerbos Policy Testing

Cerbos test files (`_test.yaml`) declare principals, resources, and expected verdicts. The critical property for deny-by-default: **principals omitted from `expected` implicitly expect `EFFECT_DENY` for all actions** [24]. Define an `unknown` role principal and omit it from `expected` to automatically assert universal denial:

```yaml
name: MCP_ToolPolicyTests
principals:
  admin:
    id: adminID
    roles: [admin]
  unknown:
    id: unknownID
    roles: [visitor]
resources:
  tool:
    id: tool1
    kind: mcp_tool
tests:
  - name: role-based tool access
    input:
      principals: [admin, unknown]
      resources: [tool]
      actions: [call, list, describe]
    expected:
      - principal: admin
        resource: tool
        actions:
          call: EFFECT_ALLOW
          list: EFFECT_ALLOW
          describe: EFFECT_ALLOW
      # 'unknown' omitted => all actions EFFECT_DENY
```

Run `cerbos compile` in CI without a running PDP [24][93]. CI options: `cerbos/cerbos-compile-action@v1` (GitHub Actions), `docker run --rm -v $(pwd):/policies ghcr.io/cerbos/cerbos:latest compile /policies` (Docker) [93]. Cerbos enforces DENY precedence: if multiple rules match, DENY wins over ALLOW [94].

### 4.2 Deny-by-Default Verification

The Cerbos Python SDK does not default to deny when the PDP is unreachable [95]. The application layer must implement a fail-closed wrapper:

```python
async def check_permission(client, principal, resource, action):
    try:
        return await client.is_allowed(action, principal, resource)
    except Exception:
        return False  # deny-by-default on PDP failure
```

Test by using `cerbos[testcontainers]` to spin up a real PDP, then stopping the container mid-test to simulate unreachability [95]. Assert that the wrapper returns deny on connection error.

Additional deny-by-default test cases [28]:
- No credentials at all: 401/403
- Malformed credentials: invalid HMAC format, truncated JWT
- Valid auth, no permission: authenticated user requesting unauthorized resource
- Policy engine unavailable: mock `ConnectionError`, assert 503 or 403
- Tenant boundary: user from org A must not access org B resources

### 4.3 Dual-Layer RBAC Enforcement

The dual-layer pattern enforces authorization at two points: (1) discovery filtering (`tools/list` returns only tools the principal can see) and (2) call-level guards (`tools/call` enforces per-action permissions) [100]. This is defense-in-depth.

```python
@pytest.mark.parametrize("role,visible_count,can_delete", [
    ("admin", 10, True),
    ("viewer", 5, False),
    ("anonymous", 0, False),
])
async def test_dual_layer_enforcement(role, visible_count, can_delete):
    principal = make_principal(role=role)
    # Layer 1: discovery filtering
    discovered = await list_resources(principal)
    assert len(discovered) == visible_count
    # Layer 2: call-level guard
    for resource in discovered:
        assert await check_access(principal, resource, "read") is True
        assert await check_access(principal, resource, "delete") is can_delete
    # Bypass attempt: direct access by ID
    if role != "admin":
        assert await check_access(principal, admin_only_resource, "read") is False
```

The ARBITER research framework demonstrated that dual-layer enforcement achieves F1 scores of 0.83-0.89, compared to 0.32-0.43 for single-layer [101]. Envoy's RBAC filter provides a shadow mode for testing new policies against live traffic without enforcement [102].

### 4.4 Concurrent Rate Limit Testing

Use `asyncio.gather` to fire bursts exceeding the rate limit and assert correct enforcement [96][97]:

```python
async def test_rate_limiter_concurrent_burst():
    limiter = RedisRateLimiter(max_requests=10, window_seconds=1, redis=redis_client)

    async def attempt_request(key: str) -> bool:
        try:
            async with limiter(key):
                return True
        except RateLimitExceeded:
            return False

    results = await asyncio.gather(
        *[attempt_request("user:123") for _ in range(50)]
    )
    allowed = sum(1 for r in results if r)
    assert allowed <= 10
```

Testing patterns [98][99]:
- **Burst testing**: N >> limit concurrent requests, assert exactly `limit` allowed
- **Window reset**: exhaust quota, wait for expiry, confirm recovery
- **Sliding window boundary**: requests straddling two windows
- **Distributed**: multiple processes against the same Redis key

For unit tests, `FakeAsyncRedis` eliminates the need for a real Redis server [51][52]. For integration tests, use `testcontainers[redis]` [111].

## 5. Session and State Management

### 5.1 FakeRedis Patterns

`FakeAsyncRedis` (v2.34.1) provides full Redis command support including INCR, EXPIRE, pipelines, and Lua scripting [51]:

```python
@pytest_asyncio.fixture
async def redis_client():
    async with fakeredis.FakeAsyncRedis() as client:
        yield client
```

For shared state across tests, use `connected_server` parameter. For isolation, create a fresh instance per test (the default) [51][52]. Avoid `app.dependency_overrides` with FakeAsyncRedis in synchronous test clients -- use `mock.patch` with `httpx.AsyncClient` instead to avoid event loop mismatches [53].

### 5.2 Circuit Breaker State Machines

Test all state transitions [54][55][56]:

1. **Closed -> Open**: Trigger `fail_max` consecutive failures, assert `current_state == "open"` and calls raise `CircuitBreakerError`
2. **Open -> Half-Open**: Advance time past `reset_timeout` (via freezegun/time-machine), assert one trial call permitted
3. **Half-Open -> Closed**: Trial call succeeds, state returns to "closed"
4. **Half-Open -> Open**: Trial call fails, state returns to "open"
5. **Exception exclusion**: Configure `exclude=[BusinessError]`, assert `fail_counter` does not increment

For distributed circuit breakers using `CircuitRedisStorage`, inject FakeRedis as the storage backend. Do not initialize Redis with `decode_responses=True` as pybreaker requires bytes [54].

Use `aiobreaker` for native async circuit breakers [55]. Inject `AsyncMock(side_effect=Exception)` as the protected function to test state transitions.

### 5.3 Session Pool Testing

Cover [57][29]:
- Acquire within capacity: session returned immediately
- Acquire at capacity: coroutine blocks (`asyncio.wait_for` with short timeout, assert `TimeoutError`)
- Release returns to pool: assert `pool.available` increments
- Eviction on idle timeout: time-mock past idle timeout, trigger sweep, assert session removed
- Concurrent acquire/release: `asyncio.gather` with N > pool size

### 5.4 Token-Encoded Session Round-Trips

Session state encoded in tokens (e.g., Fernet-encrypted session data) requires round-trip testing. Encrypt session data, transmit through the gateway, decrypt on the other side, assert data integrity. Test with `decrypt_at_time()` for TTL [45]. Test that tampered tokens produce `InvalidToken` rather than corrupted data.

## 6. Integration Testing

### 6.1 Stub MCP Servers as Fixtures

Build stub upstream servers using FastMCP for predictable, deterministic test targets [2]:

```python
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

async def test_tool_discovery(stub_server):
    async with Client(stub_server) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools} == {"echo", "add"}
```

For gateway aggregation testing with multiple upstream servers mounted via `FastMCPProxy` [108][109]:

```python
@pytest.fixture
async def gateway_with_stubs():
    weather = make_stub_server({"get_forecast": lambda city: f"Sunny in {city}"})
    github = make_stub_server({"list_repos": lambda user: [f"{user}/repo1"]})

    async with run_server_async(weather) as weather_url, \
               run_server_async(github) as github_url:
        gateway = create_gateway_mcp(Settings(
            servers={"weather": ServerConfig(url=weather_url),
                     "github": ServerConfig(url=github_url)}
        ))
        async with Client(gateway) as client:
            yield client

async def test_namespace_prefixed_tools(gateway_with_stubs):
    tools = await gateway_with_stubs.list_tools()
    names = {t.name for t in tools}
    assert "weather_get_forecast" in names
    assert "github_list_repos" in names
```

### 6.2 HTTP Transport via run_server_async

When testing real Streamable HTTP behavior (header propagation, `Mcp-Session-Id` tracking, SSE reconnection), use `run_server_async` from `fastmcp.utilities.tests` [7][104]:

```python
from fastmcp.utilities.tests import run_server_async

async def test_streamable_http_round_trip():
    server = FastMCP("HTTPTest")
    @server.tool()
    def greet(name: str) -> str:
        return f"Hello, {name}"

    async with run_server_async(server, transport="streamable-http") as url:
        async with Client(url) as client:
            result = await client.call_tool("greet", {"name": "World"})
            assert result.data == "Hello, World"
```

`run_server_in_process` provides subprocess isolation when testing process boundary behavior or env var injection. It handles port allocation, startup polling (50ms -> 100ms -> 200ms backoff, 30 attempts), and cleanup [7].

### 6.3 Stdio Subprocess Testing

For gateway scenarios proxying to upstream stdio servers, `Client` natively handles subprocess management [3]:

```python
async def test_stdio_upstream():
    async with Client("python my_stdio_server.py") as client:
        tools = await client.list_tools()
        assert len(tools) > 0
```

For lower-level raw JSON-RPC framing tests over stdio, the testcontainers pattern demonstrates direct socket communication with Docker containers running stdio MCP servers [105].

### 6.4 Recording and Replay

`mcp-recorder` provides VCR-like cassette recording for MCP interactions [107]:

```python
@pytest.mark.mcp_cassette("cassettes/weather_flow.json")
async def test_weather_flow(mcp_replay_url):
    async with Client(mcp_replay_url) as client:
        result = await client.call_tool("get_forecast", {"city": "NYC"})
        assert "sunny" in result.content[0].text.lower()
```

Cassettes support credential redaction (`--redact-env API_KEY`) and configurable matching strategies (method+params, sequential, strict) [107].

### 6.5 Docker Compose Environments

A full integration test environment for the gateway requires Redis, Cerbos PDP, and upstream MCP stubs.

**Testcontainers approach** (programmatic, per-test isolation) [111][95]:

```python
from testcontainers.redis import RedisContainer
from cerbos.sdk.container import CerbosContainer

@pytest.fixture(scope="session")
def redis():
    with RedisContainer() as container:
        yield container.get_client()

@pytest.fixture(scope="session")
def cerbos():
    with CerbosContainer() as container:
        container.with_volume_mapping("./policies", "/policies")
        container.wait_until_ready()
        yield container.http_host()
```

The `cerbos[testcontainers]` extra provides `CerbosContainer` with `wait_until_ready()` and `http_host()` [95]. Redis containers auto-assign random free ports [111]. Testcontainers currently lacks `wait_for_healthcheck()` -- poll `container.get_wrapped_container().reload()` and check `.health` [113].

**Docker Compose approach** (realistic multi-service topology) [116][117]:

The `pytest-docker` plugin calls `docker compose up --wait` and provides `docker_services.wait_until_responsive()` for custom readiness probes [116]. Docker Compose v5.0 introduced separate `start_interval` and `interval` healthcheck parameters for rapid startup polling [118]. Chain `depends_on` conditions: gateway depends on Redis, Cerbos, and upstream stubs, all with `condition: service_healthy` [118].

**Trade-off**: Testcontainers excels for programmatic control and per-test isolation. Docker Compose excels for complex interdependent services reusable across local dev, CI, and staging. A hybrid is common: Compose defines the topology, pytest-docker manages the lifecycle [120].

## 7. Testing Tools Landscape

| Tool | Type | Transport | CI Mode | Gateway Testing |
|---|---|---|---|---|
| **MCP Inspector** [39][73] | Interactive debugger | stdio, SSE, Streamable HTTP | `--cli` flag, JSON output | Point at gateway URL; no routing verification |
| **mcp-validator** [65] | Conformance suite | Streamable HTTP | JSON/HTML reports | Best for protocol compliance; opaque to routing |
| **@mcp-testing/server-tester** [75] | Playwright-based | stdio, HTTP | Native Playwright CI | Snapshot testing, LLM-as-judge evals |
| **FastMCP Client** [2] | In-memory unit test | In-process | Native pytest | Best for stub server and proxy logic |
| **mcp-recorder** [107] | Record/replay | stdio, HTTP | Cassette files | Deterministic CI without credentials |
| **mcpc (Apify)** [77] | CLI client | stdio, Streamable HTTP | `--json` output | Persistent sessions, OAuth 2.1 |
| **MCP Testing Framework** [80] | Multi-model eval | HTTP | Reports | Validates tool descriptions across LLM providers |

No existing tool validates gateway-specific semantics (upstream routing, session multiplexing, stream fan-out, ID rewriting). Custom test harnesses are required for these.

## 8. Recommendations for CommandClaw-MCP

### 8.1 Test File Structure

```
commandclaw-mcp/
  tests/
    conftest.py                     # shared fixtures (stub servers, redis, cerbos)
    unit/
      test_hmac_middleware.py        # HMAC verification, nonce replay, timestamp
      test_phantom_token.py          # credential isolation, header stripping
      test_fernet_encryption.py      # encrypt/decrypt round-trips, TTL, rotation
      test_rbac_policy.py            # Cerbos mock, dual-layer, deny-by-default
      test_rate_limiter.py           # concurrent burst, window reset
      test_circuit_breaker.py        # state machine transitions
      test_session_pool.py           # acquire/release/eviction
    protocol/
      test_initialize.py             # handshake, capability negotiation
      test_message_id.py             # ID preservation through proxy
      test_notification.py           # notification passthrough, no-response
      test_capability_gating.py      # absent capabilities correctly hidden
      test_sse_resumability.py       # Last-Event-ID, per-stream replay
      test_protocol_version.py       # MCP-Protocol-Version header enforcement
    integration/
      test_gateway_aggregation.py    # multi-server mount, namespace prefixing
      test_http_transport.py         # real Streamable HTTP round-trips
      test_stdio_transport.py        # subprocess-based upstream servers
      test_security_stack.py         # HMAC + phantom token + RBAC composed
    e2e/
      docker-compose.test.yml        # Redis + Cerbos + stubs
      test_full_stack.py             # Docker Compose-based end-to-end
  cerbos/
    policies/
      mcp_tool.yaml                  # resource policy
      tests/
        mcp_tool_test.yaml           # policy test file
```

### 8.2 Key Fixtures

```python
# conftest.py
import fakeredis
import pytest
import pytest_asyncio
from fastmcp import FastMCP, Client
from fastmcp.utilities.tests import run_server_async

@pytest.fixture
def stub_echo_server():
    server = FastMCP("StubEcho")
    @server.tool()
    def echo(text: str) -> str:
        return f"echo:{text}"
    return server

@pytest_asyncio.fixture
async def redis_client():
    async with fakeredis.FakeAsyncRedis() as client:
        yield client

@pytest.fixture
def mock_cerbos(monkeypatch):
    """Cerbos client that allows everything for admin, denies for others."""
    from unittest.mock import AsyncMock
    allowed = {"admin": {"call", "list", "describe"}, "viewer": {"list", "describe"}}
    async def fake_check(principal, resource, action):
        return action in allowed.get(principal.roles[0], set())
    monkeypatch.setattr("commandclaw_mcp.auth.cerbos_client.check",
                        AsyncMock(side_effect=fake_check))
```

### 8.3 CI Pipeline

```yaml
# .github/workflows/test.yml
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest tests/unit tests/protocol -x --timeout=30

  cerbos-policy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: cerbos/cerbos-setup-action@v1
      - uses: cerbos/cerbos-compile-action@v1
        with: { policyDir: cerbos/policies }

  integration:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7
        ports: ["6379:6379"]
        options: --health-cmd "redis-cli ping" --health-interval 10s
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest tests/integration -x --timeout=60

  conformance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e ".[dev]" && python -m commandclaw_mcp &
      - run: |
          pip install mcp-testing
          python -m mcp_testing.scripts.http_compliance_test \
            --server-url http://localhost:8088 \
            --protocol-version 2025-06-18
```

### 8.4 Priorities

1. **Start with in-memory stub tests** (`Client(server)`) for gateway aggregation logic. These are fast, deterministic, and catch the most common bugs.
2. **Add protocol compliance tests** next -- message ID preservation, capability gating, and notification passthrough are the most likely sources of gateway-specific bugs.
3. **Run mcp-validator** against the gateway's HTTP endpoint in CI for baseline spec compliance.
4. **Test security layers independently** before composing them. Mock the policy engine when testing HMAC; mock HMAC when testing RBAC.
5. **Add Docker Compose e2e tests last** -- they are slowest but catch real integration failures (Redis connection pooling, Cerbos PDP startup, network timeout edge cases).

## Discussion

The testing landscape for MCP gateways is immature relative to traditional API gateway testing. No existing tool validates the gateway-specific concerns of session multiplexing, upstream routing, or ID rewriting. This means custom test harnesses -- built from FastMCP stubs and mcp-proxy's parity testing pattern -- are the primary verification mechanism for gateway correctness.

A tension exists between test isolation and fidelity. In-memory transports provide speed and determinism but skip HTTP-level concerns (header propagation, SSE framing, session ID management). `run_server_async` bridges this gap but still runs in-process. Docker Compose provides the highest fidelity but is 10-100x slower. The recommended approach layers all three: in-memory for unit/protocol tests, in-process HTTP for integration tests, Docker Compose for end-to-end validation.

Python's limitations for security testing are worth acknowledging. Memory zeroing is unreliable due to immutable strings and GC behavior [60][62]. Timing attack verification is impractical in CI [22]. The practical approach is linting for correct primitives (`hmac.compare_digest`, Fernet, bytearray) combined with architectural patterns (phantom tokens, deny-by-default wrappers) tested at the integration level.

## Conclusion

Testing an MCP gateway requires verification across four domains: protocol compliance (message IDs, capabilities, SSE resumability), security (HMAC, phantom tokens, key rotation, memory zeroing), authorization and rate limiting (Cerbos policies, deny-by-default, concurrent burst testing), and integration (stub servers, Docker environments, end-to-end flows). The most impactful patterns are mcp-proxy's parametrized parity testing for proxy correctness, FastMCP's `Client(server)` for fast stub-based tests, Cerbos `_test.yaml` for policy verification without a running PDP, and testcontainers for programmatic Docker lifecycle in integration tests. The primary gap in the ecosystem is gateway-specific tooling -- no existing conformance suite validates session multiplexing, upstream routing, or stream fan-out. Until such tooling emerges, custom test harnesses built from the patterns in this paper are the path forward for CommandClaw-MCP.

## References

See [mcp-gateway-testing-references.md](mcp-gateway-testing-references.md) for the full bibliography.
In-text citations use bracketed IDs, e.g., [1], [2].
