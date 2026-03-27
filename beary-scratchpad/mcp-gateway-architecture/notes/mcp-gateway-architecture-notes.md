# MCP Gateway Architecture — Notes

## General Understanding

### Q1: How does the MCP protocol work at the transport level?

### Protocol Foundation: JSON-RPC 2.0 over UTF-8

MCP uses **JSON-RPC 2.0** as its wire format [1][5]. All messages MUST be UTF-8 encoded [1]. The protocol defines three message types at the JSON-RPC layer [5]:

- **Requests**: contain `jsonrpc`, `id`, `method`, and optional `params`. The `id` field is required for response correlation -- a proxy MUST preserve this identifier when forwarding [5].
- **Responses**: contain `jsonrpc`, `id`, and either `result` or `error`. Must echo the original request's `id` [5].
- **Notifications**: contain `jsonrpc` and `method` but deliberately omit `id`. They generate no response -- critical for proxy implementations to avoid blocking on acknowledgment [5].

Standard JSON-RPC error codes apply: `-32700` (parse error), `-32600` (invalid request), `-32601` (method not found), `-32602` (invalid params), `-32603` (internal error), and `-32000` to `-32099` for protocol-specific errors [5].

Batch operations (sending an array of requests) are supported per JSON-RPC 2.0; proxies must handle partial failures where some requests succeed and others error [5].

The protocol is explicitly **stateful** -- connections maintain negotiated state from initialization through shutdown [1][4].

### Transport Layer Overview

The MCP spec (version 2025-11-25) defines two standard transports [1]:

1. **stdio** -- communication over standard input/output of a subprocess
2. **Streamable HTTP** -- HTTP-based transport with optional SSE streaming

A third transport, **HTTP+SSE**, existed in protocol version 2024-11-05 but was deprecated in the 2025-03-26 spec revision [2][6]. Clients SHOULD support stdio whenever possible [1].

Custom transports are permitted, provided they preserve the JSON-RPC message format and lifecycle requirements [1].

### stdio Transport

**Architecture**: The client launches the MCP server as a **child subprocess**. Communication occurs through the process's stdin (client-to-server) and stdout (server-to-client) [1].

**Message framing**: Messages are delimited by **newlines** and MUST NOT contain embedded newlines [1]. Each message is a complete, single-line JSON-RPC request, notification, or response. There is no Content-Length header framing (unlike LSP) -- it is pure newline-delimited JSON [1].

**Stream discipline**:
- Server MUST NOT write anything to stdout that is not a valid MCP message [1].
- Client MUST NOT write anything to the server's stdin that is not a valid MCP message [1].
- Server MAY write UTF-8 strings to **stderr** for logging (informational, debug, error) [1].
- Client MAY capture, forward, or ignore stderr and SHOULD NOT assume stderr output indicates error conditions [1].

**Connection lifecycle**:
- Client launches subprocess -> exchanges messages via stdin/stdout -> closes stdin to signal shutdown [1][4].
- Shutdown: client closes stdin, waits for server exit, sends SIGTERM if needed, then SIGKILL as last resort [4].
- Server MAY initiate shutdown by closing its stdout and exiting [4].

**Performance characteristics**: Microsecond-level latency (<1ms), ~10MB memory per connection, 10,000+ ops/sec throughput, but limited to a single client [3]. Eliminates network stack overhead entirely [3].

**When to use**: Local CLI tools, desktop applications with embedded servers, development environments, single-client automation scripts [3].

### Legacy HTTP+SSE Transport (2024-11-05, Deprecated)

**Dual-endpoint architecture**: The server MUST provide two separate endpoints [6][7]:
1. An **SSE endpoint** (e.g., `/sse`) -- client connects via HTTP GET to establish a long-lived Server-Sent Events stream for receiving server messages.
2. A **POST endpoint** (e.g., `/sse/messages`) -- client sends JSON-RPC messages as HTTP POST requests.

**Connection flow** [6][7]:
1. Client opens SSE connection to the SSE endpoint via GET.
2. Server sends an `endpoint` event containing the URI for the POST endpoint.
3. All subsequent client messages are sent as HTTP POST to that endpoint.
4. Server messages arrive as SSE `message` events with JSON-encoded data.

**Key limitations that motivated deprecation** [2]:
- **Dual-endpoint complexity**: Developers had to coordinate state across disconnected endpoints and implement correlation logic between requests and responses -- "like trying to have a conversation using two phones" [2].
- **Scalability**: Long-lived SSE connections are resource-intensive, each consuming resources even during idle periods [2].
- **No built-in resumability**: If an SSE connection dropped during processing, responses were lost with no recovery mechanism [2].
- **HTTP/2 and HTTP/3 incompatibilities**: SSE implementations struggled with modern HTTP protocols, limiting infrastructure optimization [2].

**Security**: Same DNS rebinding protections required -- Origin header validation, localhost binding, authentication [6].

### Streamable HTTP Transport (Current Standard)

**Single-endpoint architecture**: The server provides ONE HTTP endpoint (the "MCP endpoint") supporting both POST and GET methods, e.g., `https://example.com/mcp` [1]. This replaces the dual-endpoint SSE model.

####.1 Client-to-Server: POST

Every JSON-RPC message from client to server is a new HTTP POST to the MCP endpoint [1]:

- **Request body**: A single JSON-RPC request, notification, or response (NOT batched at the HTTP level) [1].
- **Required headers**: Client MUST include `Accept: application/json, text/event-stream` [1].
- **For notifications/responses from client**: Server returns `202 Accepted` with no body on success; an HTTP error status (e.g., 400) with optional bodyless JSON-RPC error on failure [1].
- **For requests from client**: Server MUST return either:
  - `Content-Type: application/json` -- a single JSON response object (simple request-response), OR
  - `Content-Type: text/event-stream` -- an SSE stream for streaming responses [1].

The client MUST support both response modes [1]. This "dynamic behavior" means simple operations use standard HTTP request-response while long-running operations automatically upgrade to SSE streaming [2].

####.2 Server-to-Client: GET (Optional SSE Listener)

Client MAY issue an HTTP GET to the MCP endpoint to open an SSE stream for receiving server-initiated messages without first sending data [1]:

- Client MUST include `Accept: text/event-stream` [1].
- Server MUST either return `Content-Type: text/event-stream` or `405 Method Not Allowed` (indicating no standalone SSE support) [1].
- Server MAY send JSON-RPC requests and notifications on this stream, but MUST NOT send responses (unless resuming a previous stream) [1].
- Server and client MAY close this stream at any time [1].

####.3 SSE Stream Behavior (within POST responses)

When a server opens an SSE stream in response to a POST [1]:
- Server SHOULD immediately send an SSE event with an event ID and empty `data` field to prime reconnection.
- Server MAY close the HTTP connection without terminating the logical SSE stream, allowing the client to "poll" by reconnecting.
- Before closing, server SHOULD send an SSE `retry` field; client MUST respect this delay before reconnecting.
- The stream SHOULD eventually include the JSON-RPC response for the original request.
- Server MAY send additional JSON-RPC requests and notifications before the response (these SHOULD relate to the originating request).
- After sending the response, server SHOULD terminate the stream.
- Disconnection SHOULD NOT be interpreted as cancellation; client SHOULD send explicit `CancelledNotification` to cancel [1].

####.4 Multiple Connections

Client MAY maintain multiple simultaneous SSE streams. Server MUST send each message on only one stream (no broadcasting) [1]. Message loss risk can be mitigated through resumability [1].

####.5 Resumability and Redelivery

Servers MAY attach `id` fields to SSE events per the SSE standard [1]:
- IDs MUST be globally unique within a session (or per-client if no session).
- IDs SHOULD encode sufficient information to identify the originating stream.
- On disconnection, client resumes via HTTP GET with `Last-Event-ID` header.
- Server MAY replay missed messages from the disconnected stream only (MUST NOT replay messages from other streams).
- Resumption is always via GET with `Last-Event-ID`, regardless of whether the original stream was POST or GET initiated [1].

Event IDs function as **per-stream cursors** [1][8].

####.6 Session Management

Sessions begin at initialization and are managed via the `Mcp-Session-Id` header [1]:

1. Server MAY assign a session ID by including `Mcp-Session-Id` in the HTTP response to the `InitializeResult` [1].
2. Session ID MUST be globally unique, cryptographically secure (UUID, JWT, or hash), containing only visible ASCII (0x21-0x7E) [1].
3. Client MUST include `Mcp-Session-Id` on ALL subsequent HTTP requests [1].
4. Server SHOULD respond `400 Bad Request` to requests missing the header (except initialization) [1].
5. Server MAY terminate sessions at any time, responding `404 Not Found` to subsequent requests with that session ID [1].
6. On receiving 404, client MUST start a new session with a fresh `InitializeRequest` (no session ID) [1].
7. Client SHOULD send HTTP DELETE to the MCP endpoint with the session ID to explicitly terminate a session. Server MAY respond `405 Method Not Allowed` if it does not support client-initiated termination [1].

####.7 Protocol Version Header

Client MUST include `MCP-Protocol-Version: <version>` (e.g., `MCP-Protocol-Version: 2025-11-25`) on all HTTP requests after initialization [1]. This is the version negotiated during initialization [1][4]. If missing, server SHOULD assume `2025-03-26` for backward compatibility. Invalid/unsupported versions get `400 Bad Request` [1].

####.8 Security Requirements

- Server MUST validate `Origin` header on all connections to prevent DNS rebinding; invalid Origin gets `403 Forbidden` [1].
- Local servers SHOULD bind to 127.0.0.1 only [1].
- Servers SHOULD implement proper authentication [1].
- Streamable HTTP supports standard HTTP auth: bearer tokens, API keys, custom headers [3].

### Initialization Lifecycle (All Transports)

The lifecycle is three-phase: Initialization -> Operation -> Shutdown [4].

**Initialization** (MUST be the first interaction) [4]:
1. Client sends `initialize` request with: `protocolVersion`, `capabilities`, `clientInfo`.
2. Server responds with: `protocolVersion` (negotiated), `capabilities`, `serverInfo`, optional `instructions`.
3. Client sends `notifications/initialized` notification.

**Version negotiation**: Client sends its latest supported version. Server responds with the same if supported, or its own latest. If client cannot support the server's version, it SHOULD disconnect [4].

**Capability negotiation**: Clients advertise `roots`, `sampling`, `elicitation`, `tasks`. Servers advertise `prompts`, `resources`, `tools`, `logging`, `completions`, `tasks`. Both parties MUST only use negotiated capabilities during operation [4].

**Timeouts**: Implementations SHOULD set per-request timeouts and issue `CancelledNotification` when exceeded. Progress notifications MAY reset the timeout clock, but a maximum timeout SHOULD always be enforced [4].

### Backward Compatibility (Streamable HTTP <-> Legacy SSE)

**Servers** wanting to support old clients should host both the legacy SSE/POST endpoints alongside the new MCP endpoint. Combining the old POST endpoint with the new MCP endpoint is possible but adds complexity [1].

**Clients** wanting to support old servers [1]:
1. Accept an MCP server URL from the user.
2. POST an `InitializeRequest` to the URL with the standard `Accept` header.
3. If it succeeds: use Streamable HTTP.
4. If it fails with 400, 404, or 405: fall back by issuing a GET to the URL, expecting an SSE stream with an `endpoint` event (old transport). Use the old HTTP+SSE transport from there.

The TypeScript SDK (v1.10.0+) supports this fallback logic [2].

### Gateway/Proxy Considerations

For an engineer building an MCP gateway proxy, key considerations include:

- **Message ID preservation**: Every response must carry the exact `id` from its request [5].
- **Notification passthrough**: Messages without `id` require no response; the proxy must not block waiting for one [5].
- **Bidirectional routing**: Servers can initiate requests to clients (e.g., `sampling/createMessage`), requiring full-duplex transport through the proxy [5].
- **Capability enforcement**: Proxy should validate messages against negotiated capabilities before forwarding [5].
- **Session affinity**: When load balancing, `Mcp-Session-Id` requires sticky sessions (e.g., `ip_hash` in nginx) [3].
- **Proxy buffering**: Nginx and similar reverse proxies must disable response buffering for SSE streams [3].
- **Heartbeats**: Implement periodic heartbeats (~30s) to prevent intermediate proxies from timing out long-lived SSE connections [3].
- **CORS**: Streamable HTTP requires proper CORS configuration; validate origins in production [3].
- **Transport bridging**: A proxy can bridge stdio servers to Streamable HTTP clients (stdio-to-HTTP proxy pattern), enabling local subprocess servers to be accessed remotely [3].

### Q2: What existing MCP gateway/proxy implementations exist?

## LANDSCAPE OVERVIEW

The MCP gateway/proxy ecosystem as of early 2026 has matured rapidly into a well-defined architectural pattern. An MCP gateway acts as a specialized reverse proxy between AI agents (clients) and MCP tool servers, centralizing credential management, tool discovery, routing, and observability [9]. The space spans from lightweight Python transport bridges to enterprise-grade Kubernetes-native platforms. Implementations exist in Python, Go, Rust, TypeScript, and .NET/C#.

Three broad categories have emerged: (1) **managed platforms** prioritizing developer velocity with pre-built integrations, (2) **security-first proxies** for regulated industries emphasizing compliance and threat detection, and (3) **infrastructure-native solutions** offering maximum control through container-native, open-source implementations [9].

---

## MAJOR IMPLEMENTATIONS

### Microsoft MCP Gateway (.NET, Kubernetes-native)

Microsoft's `mcp-gateway` is a reverse proxy and management layer designed for Kubernetes environments, implementing a **dual-plane architecture** [10]:

- **Data Plane**: Handles runtime MCP request routing. Adapters direct traffic to specific MCP servers via `/adapters/{name}/mcp` endpoints using streamable HTTP. A **Tool Gateway Router** at `/mcp` dynamically routes tool execution requests by consulting registered tool definitions and forwarding to matching tool servers [10].
- **Control Plane**: RESTful management APIs for adapter lifecycle (CRUD at `/adapters`) and tool registration/orchestration (at `/tools`) [10].

**Session management** uses a distributed session store (production mode) with session affinity ensuring all requests with a given `session_id` route to the same MCP server instance. The Tool Gateway Router is deployed as a Kubernetes StatefulSet behind a headless service for horizontal scaling [10][11].

**Authentication**: Bearer token validation with Azure Entra ID integration and RBAC. Roles like `mcp.admin` and `mcp.engineer` control both data and control plane access. Write access is restricted to resource creators and administrators [10].

**Language**: .NET/C#, with packages `Microsoft.McpGateway.Service` and `Microsoft.McpGateway.Tools` [10].

### Docker MCP Gateway (Go)

Docker's MCP Gateway runs MCP servers in **isolated Docker containers** with restricted CPU (1 core), memory (2 GB), and no host filesystem access by default [12][13]. Written in Go (1.24+), it operates as a Docker CLI plugin (`docker-mcp`) [13].

**Multi-server aggregation**: Supports servers from multiple sources -- Docker catalog references (`catalog://`), Docker images (`docker://`), MCP Registry URLs, and local YAML files. The gateway dynamically discovers and aggregates tools, prompts, and resources across all running servers [13].

**Credential management**: Leverages Docker Desktop's native secrets store rather than environment variables. Secrets can be exported for cloud deployments via `docker mcp secret export`. Built-in OAuth flow support via `docker mcp oauth` manages token-based authentication without exposing credentials in config files [13].

**Profiles**: A grouping mechanism for organizing servers, ensuring consistent configuration across multiple AI clients (VS Code, Cursor, Claude Desktop) [13].

**Transport**: Supports stdio (default, single-client) and streaming transport (`--transport streaming`) for multi-client deployments [13].

### Envoy AI Gateway (Go + Envoy)

Envoy AI Gateway's MCP implementation is a **lightweight Go server** that leverages Envoy's existing networking stack for connection management, load balancing, circuit breaking, rate-limiting, and observability [14].

**Distinctive session management**: Instead of a centralized session store, Envoy uses a **token-encoding architecture**. When an agent initializes an MCP session, the gateway establishes upstream sessions with backend servers, then builds a compact encrypted description of these upstream sessions wrapped into a self-contained client session ID. Encryption uses KDF (key-derivation functions). Any gateway replica can decode the session ID to route traffic without database lookups [14][15].

Performance: Default configuration with 100k KDF iterations adds tens of milliseconds per new session; tuned to ~100 iterations it drops to 1-2ms [15]. This enables straightforward horizontal scaling with no state synchronization between replicas [15].

**Multi-server aggregation**: Dynamically aggregates, merges, and filters messages and streaming notifications from multiple MCP servers. Tool routing directs invocations to appropriate backends while filtering tools based on gateway policies [14].

**Authentication**: Two layers -- gateway-level OAuth for fine-grained AuthZ over tool invocations, and built-in upstream authentication primitives for credential injection to external MCP servers using existing Envoy Gateway patterns [14].

### IBM ContextForge (Python, FastAPI)

ContextForge is an **open-source registry and proxy** built on FastAPI + Pydantic that federates not just MCP servers but also REST APIs, gRPC services, and A2A protocol implementations into a unified MCP-compliant interface [16].

**Multi-transport exposure**: Simultaneously exposes services over HTTP/SSE, JSON-RPC, WebSocket, stdio, and Streamable HTTP -- clients choose their preferred transport without backend changes [16].

**Credential management**: Encryption at rest using `AUTH_ENCRYPTION_SECRET`, support for Basic/JWT/OAuth 2.0/OIDC, user-scoped token isolation per session, upstream passthrough via `X-Upstream-Authorization` header, and query parameter authentication [16].

**Governance**: RBAC with team management, tool-level and gateway-level rate limiting, metadata tracking with audit trails, and OpenTelemetry-based observability with OTLP protocol support [16].

**Python stack**: Async SQLAlchemy ORM, orjson serialization, structured JSON logging, 40+ modular services, pluggable cache (Redis or in-memory). Supports SQLite (dev), PostgreSQL/MariaDB (production) [16].

**Scaling**: Redis-backed session affinity, MCP session pooling, tool lookup caching, parallel session cleanup via asyncio, and DNS-SD auto-discovery for federated gateway detection across multi-cluster Kubernetes environments [16].

### Agentic Community MCP Gateway & Registry (Python, FastAPI)

A comprehensive Python/FastAPI platform functioning as an MCP Server Gateway, MCP Server Registry, and Agent Registry/A2A Hub [17].

**Multi-server aggregation via Virtual MCP Servers**: Aggregates tools, resources, and prompts from multiple backends into unified endpoints with tool aliasing to resolve naming conflicts, version pinning, session multiplexing (one client session maps to N backend sessions transparently), per-tool access control via scopes, and 60-second caching for list operations [17].

**Authentication**: Supports Keycloak, Microsoft Entra ID, and Okta as identity providers. Implements OAuth 2.0 2-legged (client credentials) and 3-legged (user delegation) flows. Fine-grained scope-based access control defines which servers, methods, and tools are accessible [17].

**Credential management**: Centralized vault integration with automatic rotation, Fernet-encrypted storage for federation scenarios, per-scope credential scoping, and credential masking in all audit logs [17].

**Tool discovery**: Vector-based semantic search (supports sentence-transformers, OpenAI, Bedrock Titan, Cohere embeddings) with hybrid keyword + embedding approach. Agents can discover tools at runtime via `POST /api/agents/discover/semantic` [17].

**Storage**: MongoDB/DocumentDB with HNSW vector indexing. Deployment via Docker Compose or AWS ECS Fargate (Terraform) [17].

### LiteLLM MCP Gateway (Python)

LiteLLM Proxy provides an MCP Gateway offering a **fixed endpoint for all MCP tools** with access control by API key, team, and organization [18].

**Configuration**: YAML-based, defining MCP servers with URL, transport type, auth type, and auth value. Supports Streamable HTTP, SSE, and stdio transports [18].

**Authentication**: Static credentials (API keys, bearer tokens, basic auth), AWS SigV4 for Bedrock, and OAuth 2.0 with automatic discovery and dynamic registration. Server-specific credentials can be forwarded using `x-mcp-{server_alias}-{header_name}` header patterns [18].

**Integration**: Transforms MCP tools into OpenAI-compatible formats for use with `/chat/completions` and `/v1/responses` endpoints [18].

---

## LIGHTWEIGHT PYTHON PROXIES AND LIBRARIES

### mcp-proxy (PyPI, Python)

The `mcp-proxy` package is a transport bridge operating in two modes [19]:
- **stdio-to-SSE/StreamableHTTP**: Enables local stdio clients (Claude Desktop) to reach remote MCP servers over HTTP.
- **SSE-to-stdio**: Exposes local stdio MCP servers over HTTP for remote access.

Supports **multiple named servers** behind a single proxy instance via `--named-server` or JSON config. Each server gets its own `/servers/<name>/` endpoint [19].

Credential handling: OAuth2 (`--client-id`, `--client-secret`, `--token-url`), bearer tokens via `API_ACCESS_TOKEN` env var, custom headers, and configurable SSL verification [19].

### FastMCP Proxy System (Python)

FastMCP (by Prefect/jlowin) provides a **native proxy pattern** for Python MCP development [20][21]:

- `ProxyProvider` / `create_proxy()` uses a **client factory pattern** for safe concurrent request handling with automatic session isolation per request [20].
- **Multi-server aggregation** via config-based composition with automatic namespacing (e.g., `weather_get_forecast`, `calendar_add_event`) [20].
- **Mount mechanism**: `server.mount(external_proxy)` adds proxied components alongside local tools, creating hybrid servers [20].
- Performance note: HTTP proxies introduce 300-500ms overhead compared to 1-2ms local execution [20].

FastMCP does **not** natively handle credential management or forwarding in the proxy layer -- this must be implemented at the application level [20].

### AWS MCP Proxy for AWS (Python)

A lightweight client-side bridge handling SigV4 authentication for AWS-hosted MCP servers [22]. Uses `aws_iam_streamablehttp_client` to create authenticated MCP clients with automatic credential signing via the standard AWS credential chain. Primarily designed for connecting to Amazon Bedrock AgentCore Gateway/Runtime [22].

---

## NON-PYTHON PROXIES OF NOTE

### MCProxy (Rust)

A Rust-based aggregation proxy connecting to multiple upstream MCP servers (stdio or HTTP) and exposing an aggregated tool list via streamable HTTP [23]. Features a two-tier middleware architecture: `ClientMiddleware` for per-server operations and `ProxyMiddleware` for aggregated resource processing. Includes tool filtering via configurable regex patterns and security middleware that inspects tool call inputs and blocks calls matching security rules. Listens for `toolListChanged` notifications from upstream servers for dynamic updates [23].

### adamwattis/mcp-proxy-server (TypeScript)

A TypeScript aggregation proxy supporting stdio and SSE transports [24]. Credentials are managed via environment variable references in JSON config -- the transport config specifies `env` arrays listing variables inherited from the parent process and passed to spawned servers, enabling credential injection without embedding secrets in config files [24].

---

## CREDENTIAL MANAGEMENT PATTERNS (CROSS-CUTTING)

The Red Hat article on MCP Gateway authentication describes three complementary patterns for credential isolation [25]:

1. **Identity-Based Tool Filtering**: An authorization component validates OAuth2 tokens, extracts permissions, and injects a signed JWT "wristband" (`x-authorized-tools` header) listing permitted tools. The MCP Broker validates this JWT before filtering tool lists. This prevents unauthorized tool discovery [25].

2. **OAuth2 Token Exchange (RFC 8693)**: The gateway exchanges broad-scoped access tokens for narrowly-scoped, server-specific tokens. Each backend MCP server receives only the audience and scopes it requires. This prevents lateral movement if a backend server is compromised [25].

3. **HashiCorp Vault Integration**: For non-OAuth2 servers, credentials are fetched from Vault using paths indexed by username and target server (e.g., `/v1/secret/data/alice/github.mcp.local`). Supports per-user PATs and API keys with graceful fallback to token exchange [25].

The general pattern across all implementations is that **the gateway centralizes credential storage and injects appropriate credentials per-request**, eliminating credential sprawl across agent codebases [9][25].

---

## SESSION MANAGEMENT APPROACHES

Two dominant patterns exist:

1. **Distributed session store** (Microsoft, ContextForge, Agentic Community): A shared store (Redis, database) maps session IDs to backend server instances. Provides strong session affinity but requires infrastructure and introduces a potential SPOF [10][16][17].

2. **Token-encoded sessions** (Envoy AI Gateway): Session state is encrypted into the client-facing session ID itself. Any gateway replica can decode and route without centralized state. Trades cryptographic overhead for operational simplicity and unlimited horizontal scaling [15].

---

## MULTI-SERVER AGGREGATION PATTERNS

Common aggregation approaches:

- **Namespace prefixing**: FastMCP prefixes tool names with server name (e.g., `weather_get_forecast`) to avoid collisions [20].
- **Tool aliasing**: Agentic Community allows explicit alias definitions to resolve naming conflicts [17].
- **Dynamic tool routing**: Microsoft and Envoy maintain a registry of tool definitions and route calls to the matching backend server [10][14].
- **Mount/compose**: FastMCP's `mount()` pattern attaches external server capabilities to a local server instance [20][21].
- **Profile-based grouping**: Docker uses profiles to organize which servers are available to which clients [13].
- **Policy-based filtering**: Envoy and MCProxy filter which tools are exposed based on gateway policies or regex patterns [14][23].

---

## KEY ARCHITECTURAL CONSIDERATIONS FOR A PYTHON GATEWAY

For an expert building an MCP gateway proxy in Python:

- **FastAPI + async is the dominant Python stack** (ContextForge, Agentic Community, LiteLLM all use it) [16][17][18].
- **FastMCP's proxy primitives** (`ProxyProvider`, `create_proxy()`, `mount()`) provide a solid foundation for tool aggregation but lack built-in credential management [20].
- **Session isolation via client factory pattern** prevents context mixing across concurrent requests [20].
- The **mcp-proxy** PyPI package handles transport bridging (stdio <-> HTTP) and can serve as a building block [19].
- **Credential isolation is a first-class concern** -- plan for encrypted storage, per-user scoping, OAuth token exchange, and Vault integration from the start [25].
- The **token-encoded session** approach from Envoy is worth studying for stateless horizontal scaling [15].
- **OpenTelemetry** is the standard observability approach across implementations [16][17].

### Q3: How do production systems implement rotating API key authentication?

## Taxonomy of Rotating Credential Patterns

Production systems implement rotating credentials for service-to-service (S2S) communication through several distinct patterns, each with different security properties:

### Static Key Rotation (Dual-Key / Overlapping Window)

The most common pattern maintains two active keys simultaneously during rotation. A new key is generated, both old and new keys authenticate requests during a grace period, then the old key is revoked [26]. The "roll key" variant performs this atomically in a single operation -- generating a new key and setting expiration on the old key simultaneously [26]. Recommended overlap windows range from 1 hour to 7 days depending on consumer update velocity [26][30].

**Implementation specifics:** Keys are typically 32-byte (256-bit) cryptographically random values, base64url-encoded, with unique IDs (UUIDs) and tracked creation/expiration timestamps. Storage typically uses HashiCorp Vault with three core operations: store, retrieve-valid, and revoke-expired [30].

### Dynamic Secrets (Just-in-Time Credentials)

HashiCorp Vault's dynamic secrets engine generates unique credentials per workload instance, bound to a TTL (typically minutes to hours). Each credential has a lease containing TTL information, renewability flags, and revocation capabilities. Once the lease expires, the secret automatically becomes invalid [31]. Unlike rotated secrets (shared across instances), dynamic secrets are unique per workload and cannot be shared, meaning revocation affects only a single instance [31].

**Critical trade-off:** Dynamic secrets create a runtime dependency on the secrets manager. If Vault becomes unavailable, applications cannot refresh credentials and will experience outages as leases expire [31]. This is a key availability vs. security trade-off for hourly rotation systems.

### Short-Lived JWT / OAuth2 Tokens

Access tokens with lifespans of minutes to hours replace static API keys. NIST SP 800-63B recommends reauthentication at least once per 30 days, but production S2S systems typically use far shorter intervals [29]. For service-to-service flows, the OAuth 2.0 client credentials grant is standard, with recommendations to use `client_secret_jwt` or `private_key_jwt` authentication (OpenID Connect Core) and sender-constrained tokens via DPoP or mTLS [29].

Refresh token rotation (issuing a new refresh token with each use) adds defense-in-depth for scenarios requiring persistent access, with four critical protections: rotation on use, client binding, periodic reauthentication, and real-time revocation [29].

### HMAC-Based Signed Requests

HMAC authentication uses a shared secret to sign request payloads per RFC 2104. The double-hash construction (inner/outer XOR operations with ipad/opad) prevents length extension attacks [32]. For rotating HMAC keys, the dual-phase approach supports both legacy and new keys simultaneously, with each key bound to specific clients or API scopes [32].

**Critical implementation detail:** Verification MUST use constant-time comparison (`hmac.compare_digest()` in Python, `crypto.timingSafeEqual()` in Node.js) to prevent timing attacks. Replay prevention requires timestamped headers within the signed payload, rejecting requests older than 5 minutes [32].

### TOTP-Style Service Authentication

TOTP (RFC 6238) extends HMAC-based OTP using the current time as a counter. Standard implementation: shared secret (Base32) + current time -> HMAC-SHA256 -> 6-digit code, rotating every 30 seconds [33]. While designed for human MFA, the pattern can be adapted for S2S auth where both endpoints share a secret and independently compute the current valid code without network exchange.

### SPIFFE/SPIRE Workload Identity (Certificate-Based)

SPIFFE issues short-lived X.509 certificates (SVIDs) containing a SPIFFE ID (e.g., `spiffe://mycompany.com/prod/serviceA`). Typical TTLs are 1 hour or less, with SPIRE agents automatically requesting fresh SVIDs before expiration [34][35]. Because certificates are so short-lived, traditional CRLs are unnecessary -- compromised workloads simply stop receiving new SVIDs, and existing ones expire quickly [34].

Trust domains use DNS-like naming, and workloads in one trust domain do NOT trust workloads from another by default. Cross-domain trust requires explicit SPIFFE Federation with shared trust anchors [34].

## Rotation Interval Analysis

### Industry Standards by Environment

| Environment | Rotation Interval | Rationale |
|---|---|---|
| High-security (PCI DSS, financial) | 30-90 days | Compliance-driven [26] |
| Standard production APIs | 90-180 days | Balance of operational cost vs. exposure [26] |
| Internal/low-risk APIs | 180-365 days | Minimal external exposure [26] |
| AWS STS temporary credentials | 15 min - 12 hours (default 1hr) | Cloud-native ephemeral [36] |
| SPIFFE SVIDs | Minutes to 1 hour | Zero-trust native [34][35] |
| Dynamic secrets (Vault) | Minutes to hours | Workload-lifecycle-bound [31] |

### The Five-Minute Problem

GitGuardian research shows the median time from credential leak to first malicious use is **five minutes** [27][28]. A 90-day rotation cycle provides 129,600 minutes of potential exposure. Even a 30-day rotation provides 43,200 minutes [27]. This fundamentally undermines static rotation as a *preventive* control -- rotation is a **lagging control** that addresses credentials after exploitation, not before [27].

**Implication for hourly rotation:** An hourly rotation reduces the exposure window to 60 minutes -- a 2,160x improvement over 90-day rotation, but still 12x longer than the attacker's median exploitation window. For a credential proxy with hourly rotation, this means rotation alone is necessary but insufficient; it must be combined with proxy-layer isolation, scope restriction, and real-time anomaly detection.

### NIST SP 800-57 Cryptoperiod Guidance

NIST defines "cryptoperiod" as the lifespan during which a cryptographic key is considered valid. Key separation is emphasized -- different keys for different functions (encryption vs. signing). Automating rotation and enforcing clear cryptoperiods via a centralized Key Management Infrastructure (KMI) reduces human errors [37]. Specific interval guidance varies by key type and use case, with symmetric keys for confidential data potentially lasting years, while signing keys rotate more frequently.

## Blast Radius Analysis

### Dimensions of Blast Radius

A compromised credential's blast radius is determined by: (a) temporal validity remaining, (b) scope of permitted operations, (c) number of systems accepting the credential, and (d) detectability of misuse [27][28].

**Static API keys** create unbounded blast radius because copies exist in multiple systems (.env files, CI/CD logs, integrations, documentation) and a complete inventory is typically unknown [27].

**Scoped short-lived tokens** bound the blast radius along all four dimensions: temporal limit (TTL), operational boundary (scope), system boundary (proxy-only validity), and identity binding (agent-specific) [38].

### The Phantom Token Pattern for Blast Radius Containment

The phantom token pattern (Curity-originated, now generalized) places a proxy between consumers and upstream APIs. Consumers authenticate with opaque, short-lived, scoped tokens. The proxy validates the token, retrieves the real credential from a vault, makes the upstream call, and returns the result. Real credentials never appear in consumer memory, logs, or environment [38][39].

A leaked phantom token provides only: temporal access (short TTL), operational access through the proxy only, scope-restricted operations, and identity-bound sessions. Versus a leaked real credential which works anywhere the upstream API accepts it, from any IP, for any operation [38].

**Key insight for credential proxy design:** "Rotation doesn't prevent the leak. The agent still holds the real key, for however long between rotations. Phantom tokens close it." [38]

### Revocation Certainty

Static keys scattered across systems cannot be revoked with certainty. The proxy model enables genuinely instant revocation: the moment a token is marked revoked, every subsequent request using it fails [27]. This is architecturally superior to key rotation for incident response.

## Implementation Patterns in Service Meshes and API Gateways

### Istio Service Mesh

Istio automates mTLS for S2S communication through Envoy sidecar proxies. The certificate provisioning flow: (1) Istio agent creates private key + CSR on workload startup, (2) istiod validates and signs the CSR, (3) Envoy requests certificates via Secret Discovery Service (SDS) API, (4) agent monitors expiration and repeats provisioning periodically for rotation [40]. Istio enforces TLS 1.2 minimum with approved cipher suites including ECDHE-ECDSA-AES256-GCM-SHA384.

**Permissive Mode** allows gradual migration by accepting both plaintext and mTLS simultaneously [40] -- analogous to the dual-key overlap window for API key rotation.

### AWS STS for Cloud-Native S2S

AWS STS AssumeRole provides temporary credentials with configurable duration: minimum 900 seconds (15 minutes), maximum 43,200 seconds (12 hours), default 3,600 seconds (1 hour) [36]. Role chaining limits sessions to a maximum of 1 hour. AWS SDKs include credential providers that automatically handle AssumeRole and refresh before expiration [36].

**By 2026, using long-lived AWS credentials is considered a major compliance liability.** IAM Roles Anywhere extends this to non-AWS workloads using X.509 certificates for temporary credential issuance [36].

Session policies grant the *intersection* of the role's identity-based policy and session policies -- they cannot elevate permissions. This enforces least-privilege at the session level [36].

### API Gateway-Managed Rotation

Key validation at the edge minimizes latency impact during rotation. No backend coordination is required, making this the simplest implementation pattern [26]. Gateway-managed keys decouple rotation operations from application deployment cycles.

## Security Trade-Offs: Availability vs. Security

### Rotation Frequency vs. Operational Complexity

| Factor | More Frequent Rotation | Less Frequent Rotation |
|---|---|---|
| Exposure window | Shorter (better) | Longer (worse) |
| Operational burden | Higher (more coordination) | Lower |
| Risk of rotation-induced outages | Higher | Lower |
| Secrets manager dependency | Stronger (availability risk) | Weaker |
| Grace period overlap surface | More frequent overlaps | Fewer overlaps |

### Dynamic vs. Rotated Secrets

Rotated secrets: lower latency (pre-created), shared across instances, longer exposure windows, simpler application logic. Dynamic secrets: unique per workload, shorter TTLs, isolated revocation impact, but higher latency (runtime request) and availability dependency on the secrets manager [31].

For a credential proxy with hourly rotation, the hybrid approach is recommended: use rotated secrets for the proxy-to-vault relationship (high availability requirement) and dynamic/phantom tokens for consumer-to-proxy relationships (high security requirement).

### Overlap Window Security Surface

During any dual-key overlap period, both old and new keys are valid. Longer overlap provides more consumer flexibility but increases the attack surface if the old key was compromised before rotation was triggered [26]. For hourly rotation, a 5-minute overlap window balances the need for clock-skew tolerance against exposure duration [30].

### Emerging Standards

**CAEP (Continuous Access Evaluation Profile)** enables longer token lifespans through real-time risk assessment and immediate revocation upon security events, shifting toward dynamic rather than static expiration models [29]. **WIMSE (Workload Identity in Multi-System Environments)** standardizes short-lived token management for cloud-native architectures [29]. These standards suggest the industry is moving toward context-aware credential lifecycle management rather than fixed-interval rotation.

## Practical Recommendations for a Credential Proxy with Hourly Key Rotation

Based on the research:

1. **Implement the phantom token pattern:** Consumers receive hourly-rotated opaque tokens; real upstream credentials live only in the proxy's vault [27][38].
2. **Use 5-minute overlap windows** with a 5-minute advance refresh buffer on the consumer side to handle clock skew and network delays [30].
3. **HMAC-sign all proxy requests** with the current token as the signing key, including timestamp, method, path, and host in the canonical string. Reject requests older than 5 minutes [32].
4. **Add scope restrictions** to each token (endpoint allowlist, rate limits, read/write permissions) to bound blast radius independently of TTL [27][38].
5. **Monitor rotation health metrics:** rotation success/failure counts, active key inventory, key age distribution, validation failure rates. Alert on rotation failures with exponential backoff retry (up to 3 attempts) [30].
6. **Plan for secrets manager unavailability:** Cache the current valid credential with a bounded grace period. If the secrets manager is down when rotation is due, extend the current key's validity by one additional interval rather than failing open [31].
7. **Never log actual keys; log key IDs** for audit trails. Separate keys by environment [30].

### Q4: What RBAC models exist for controlling tool access in agent systems?

## Why Traditional RBAC Fails for AI Agents

Traditional RBAC assigns static roles with fixed permission sets -- a model fundamentally mismatched to AI agent behavior. Three core deficiencies emerge:

**Over-permissioning**: Unlike humans, agents lack contextual judgment. An agent with excessive permissions will "relentlessly try to achieve" goals using all available access, making prompt injection attacks significantly more dangerous [41]. Static roles assume human restraint that agents do not possess.

**Role explosion**: Creating narrow roles like "file-reader-agent-role-for-project-x" leads to unmanageable proliferation. RBAC grants permissions to roles, not tasks, while agents need "hyper-specific, short-lived access patterns that static roles cannot express" [41].

**Machine-speed risk amplification**: Agents execute orders of magnitude faster than humans -- what causes "limited damage before someone notices" with a human becomes catastrophic within seconds as agents "bulk-edit or delete thousands of records" before alerts fire [41].

The Oso analysis proposes five required capabilities for agent authorization: (1) automated, task-scoped least privilege, (2) real-time context evaluation, (3) continuous monitoring with explainability, (4) instant containment (one-click revocation), and (5) a unified governance plane across all agents and tools [41].

## Access Control Model Taxonomy: RBAC, ABAC, PBAC, ReBAC

**RBAC** assigns users/agents to roles that map to permissions. Simple and predictable but creates role sprawl when complexity grows [42].

**ABAC** evaluates access dynamically using user attributes, resource metadata, and environmental context. Handles nuanced scenarios (e.g., "manager can approve expenses only below $1000 AND only in their department") but is harder to audit [42].

**PBAC** externalizes authorization to a centralized policy engine. All services query one decision point. Prevents drift -- e.g., one service enforcing "$10K limit" while another allows unlimited approvals. PBAC is especially critical for AI agents operating across distributed services [42].

**ReBAC** (Relationship-Based Access Control) evaluates entity relationships (e.g., "user owns this document" or "agent was delegated by this manager"). Permit.io implements this via a "Google Zanzibar-inspired relationship graph" enabling "real-world delegation and multi-hop access chains" [43].

For agent systems, the recommendation is a **hybrid approach**: RBAC for coarse role assignment, ABAC conditions for fine-grained context, enforced via a centralized PBAC engine [42] [44].

## "Agentic RBAC" -- The Emerging Model

The term "Agentic RBAC" describes the security paradigm specifically for autonomous AI agent API access. It must be "dynamic, context-aware, and auditable" [45]. Core differences from traditional RBAC:

- An agent's functional scope changes moment-to-moment based on current task
- A request that begins as read-only can evolve into a code-generation exercise needing write rights
- Every tool invocation and generated SQL/code/HTTP request should route through an external authorization service where "the policy, not the model, decides whether actions run" [45]

## MCP Specification: Authorization Foundation

The MCP spec (draft, updated 2025-11-25) defines authorization at the transport level using OAuth 2.1 [46]:

**Key roles**: MCP server = OAuth 2.1 resource server; MCP client = OAuth 2.1 client; authorization server issues tokens. Authorization is OPTIONAL but when supported, HTTP transports SHOULD conform.

**Scopes and tool access**: MCP servers SHOULD include a `scope` parameter in `WWW-Authenticate` headers to indicate required scopes. Clients MUST treat challenged scopes as authoritative. Servers can dynamically issue scopes not listed in `scopes_supported` [46].

**Step-up authorization**: When a client has a token but needs additional permissions, the server returns `403 Forbidden` with `error="insufficient_scope"` and the required scopes. Clients then perform a step-up authorization flow to obtain a new token [46].

**Default scopes (SEP-835, Nov 2025)**: Standardizes baseline OAuth scope names across the MCP ecosystem, making permissions "predictable across the ecosystem" [47].

**Client credentials (SEP-1046)**: Adds M2M OAuth for headless agents -- "cron jobs, background agents, internal automations, or agent-to-agent setups" [47].

**Enterprise IdP controls (SEP-990/XAA)**: Routes auth through corporate identity providers. The IdP evaluates policy rules (e.g., "Is Engineering allowed to use Claude to access Asana?"), issues a temporary Identity-JAG token, and the MCP server validates it. This gives enterprises "centralized admin control, no consent fatigue" [48].

## MCP Tools Specification: The Filtering Surface

The MCP tools spec (2025-06-18) defines `tools/list` and `tools/call` as the two primary endpoints [49].

**Critical architectural point**: The spec itself does NOT mandate per-client tool filtering. The `tools/list` response returns all tools the server exposes. Filtering is an implementation concern left to servers and gateways.

**`notifications/tools/list_changed`**: Servers that declare `listChanged` capability can notify clients when the tool list changes. This enables dynamic tool filtering -- after evaluating a client's permissions, the server can emit this notification to present a filtered tool set [49].

**Security requirements**: Servers MUST validate all tool inputs, implement proper access controls, rate limit invocations, and sanitize outputs. Clients SHOULD prompt for user confirmation on sensitive operations [49].

**Tool annotations**: Tools carry optional `annotations` for behavior metadata, but clients MUST treat these as untrusted unless from trusted servers [49].

## MCP Server Tool Filtering Implementation Patterns

### Pattern A: Discovery-Time Filtering (ScopeFilterMiddleware)

The most detailed implementation comes from CodiLime's network automation MCP server [50]:

**Scope vocabulary**: `mcp:<server>:<action>` with action levels: `read`, `probe`, `write`.

**Role bundling**: Three roles aggregate scopes -- `net-viewer` (read), `net-operator` (read + probe), `net-admin` (all).

**Discovery filtering via middleware**: `ScopeFilterMiddleware` inspects caller JWT scopes before returning the tool list. Agents only discover tools they're authorized to use, "constraining the LLM's reasoning space before any action attempts" [50].

**Call-time enforcement via decorator**:
```python
@mcp.tool()
@require_scope("mcp:ctrl-plane:write")
def set_interface_state(device: str, interface: str, state: str) -> str:
    ...
```
The decorator retrieves the JWT from request context, checks scope membership, and denies with audit logging if the scope is absent [50].

**Dual-layer defense**: "Neither control is sufficient on its own. Discovery filtering without call-time enforcement can be bypassed by an attacker who skips the agent and sends raw HTTP requests" [50].

### Pattern B: External PDP (Cerbos)

Cerbos integrates as a Policy Decision Point for MCP servers [51] [52]:

1. Server identifies all available tools
2. Queries Cerbos with user identity (ID + roles) for each tool
3. Receives allow/deny per tool
4. Enables permitted tools, disables restricted ones
5. Calls `server.sendToolListChanged()` to notify client

**YAML policy example** [52]:
```yaml
resourcePolicy:
  resource: "mcp::expenses"
  rules:
    - actions: ["list_expenses"]
      effect: EFFECT_ALLOW
      roles: ["admin", "manager", "user"]
    - actions: ["approve_expense", "reject_expense"]
      effect: EFFECT_ALLOW
      roles: ["admin", "manager"]
    - actions: ["delete_expense"]
      effect: EFFECT_ALLOW
      roles: ["admin"]
```

**ABAC conditions** extend role checks with attribute expressions [52]:
```yaml
condition:
  match:
    expr: request.resource.attr.amount < 1000
```

**Deny-by-default**: Agent sessions start with no tools enabled; tools are selectively enabled based on policy evaluation [51].

### Pattern C: MCP Gateway Proxy

Multiple gateway products implement tool filtering as a proxy layer:

**Bifrost**: Virtual Keys enforce strict allow-lists per consumer. A "billing support key" can access only `check-status` from the billing client while a "support key" gets full tool access. Built in Go with microsecond overhead at 5,000 req/s [53].

**Lunar.dev MCPX**: Tool-level RBAC at individual tool granularity. Administrators can lock parameters and rewrite tool descriptions. ~4ms p99 latency [53].

**Permit MCP Gateway**: Auto-generates OPA/Rego policies by inspecting upstream MCP server tools. Supports RBAC + ABAC + ReBAC via a Zanzibar-inspired relationship graph. Requires an `identify_self` handshake that "fingerprints the agent and continuously monitors for drift" to prevent privilege escalation. Sub-10ms policy decisions with real-time updates via OPAL [43].

### Pattern D: Virtual MCP (vMCP) / Curated Tool Sets

Platform teams use vMCP to "compose curated tool sets exposing only the specific tools each team or role needs, not the full surface area of every connected MCP server" [54]. Recent enhancements include on-demand tool discovery where "agents no longer receive hundreds of tool descriptions in context" -- instead tools are discovered at request time via hybrid semantic + keyword search, surfacing only relevant tools (up to 8 by default), cutting token usage by 60-85% [54].

## Capability-Based Delegation (Alternative to RBAC)

The MCP Delegation Gateway proposes a cryptographic capability-based model where "delegated permissions can only shrink -- never expand" [55]. Unlike RBAC's role-to-permission mapping, this uses:

- Signed, tamper-evident receipts for every authorization decision
- A 7-step verification pipeline: signature verification, chain reconstruction, trusted root validation, expiry checking, revocation verification, permission attenuation, action authorization
- Monotonic capability reduction ensuring downstream agents receive strictly narrower permissions than their delegators

This model is particularly suited to agent-to-agent delegation chains where RBAC role assignments become meaningless.

## Agent Platform Native Tool Access Control

### LangChain

LangChain treats tools as functions that agents can invoke. Authorization is NOT built into the framework but is achieved through integration patterns [56] [57]:

- **Delegated access**: Agents access resources on behalf of users via OAuth Auth Code Flow and On-Behalf-Of (OBO) token flow
- **Direct access**: Agents operate autonomously via Client Credentials Flow
- LangChain MCP Adapters connect agents to external auth systems like Permit.io, converting access request/approval tools into LangChain-compatible tools

The Permit.io "four-perimeter" model for LangChain defines: (1) Prompt Protection (identity validation), (2) RAG Filtering (document access control), (3) Secure External Access (tool authorization), and (4) Response Enforcement (output redaction) [57].

### CrewAI

CrewAI uses a direct tool-assignment model: agents receive a `tools=[...]` list at instantiation [58]:
```python
researcher = Agent(
    role="AI Technology Researcher",
    goal="Research the latest AI developments",
    tools=[search_tool, wiki_tool],
)
```

This is static, per-agent tool scoping with no built-in dynamic RBAC mechanism. The framework handles orchestration "through defined roles and processes, ensuring consistency and auditability across agents" but relies on developer discipline for tool restriction [58].

## Policy Engines for Agent Authorization

**OPA (Open Policy Agent)**: General-purpose policy engine using Rego language. Evaluates structured data (JSON) against declarative policies. Supports RBAC, ABAC, and ReBAC. Used by Permit MCP Gateway to auto-generate tool authorization policies [43] [59].

**Cerbos**: Purpose-built authorization PDP with <1ms decision time. YAML-based policies supporting RBAC + ABAC + PBAC. Dedicated MCP server integration for dynamic tool authorization with live policy reloading [51] [52].

**Oso/Polar**: Alternative policy engine with its own language (Polar). Can express RBAC, ABAC, ReBAC, or hybrid models. AI workflows filter embeddings and search results through Oso to ensure agents see only authorized data [42].

## Architectural Recommendations for Per-Agent MCP RBAC

Based on the research, a robust per-agent RBAC system for MCP tool visibility should implement:

1. **Dual-layer enforcement**: Discovery filtering (constrain `tools/list` responses) AND call-time checks (`tools/call` enforcement). Neither alone is sufficient [50].

2. **Externalized policy engine**: Use OPA, Cerbos, or equivalent PDP. Express policies declaratively in YAML/Rego, not in application code [51] [52].

3. **Scope-based OAuth integration**: Map MCP scopes to tool permissions using `mcp:<domain>:<action>` convention. Leverage MCP's built-in `WWW-Authenticate` scope challenges and step-up authorization [46] [50].

4. **Dynamic tool list updates**: Use `notifications/tools/list_changed` to re-filter tool lists when permissions change mid-session [49] [52].

5. **Deny-by-default**: Start agent sessions with no tools. Selectively enable based on policy evaluation [51].

6. **Context-aware ABAC conditions**: Supplement role checks with attribute conditions (amount thresholds, department matching, time-of-day restrictions) [52].

7. **Audit every decision**: Log all allow/deny decisions with principal, resource, action, and policy outcome for compliance [50] [51].

8. **Tool design granularity matters**: "If a tool accepts a free-form command string passed directly to a device, it cannot be meaningfully secured by scope alone" [50]. Tools must be specific and well-scoped for authorization to work.

### Summary

The four research questions converge on a coherent architecture for an MCP gateway proxy. At the transport level (Q1), MCP uses JSON-RPC 2.0 over Streamable HTTP as its current standard, with session management via `Mcp-Session-Id` headers, optional SSE streaming for long-running operations, and built-in resumability -- all of which a gateway must faithfully proxy while preserving message IDs, session affinity, and bidirectional routing. The existing implementation landscape (Q2) confirms that FastAPI + async Python is the dominant stack for Python gateways, with credential centralization, multi-server aggregation via namespace prefixing or virtual MCP servers, and either distributed session stores or token-encoded sessions as the two scaling strategies. For credential security (Q3), the research strongly favors the phantom token pattern -- where consumers receive short-lived opaque tokens while real upstream credentials remain exclusively in the proxy's vault -- over simple key rotation alone, since the median leak-to-exploit time of five minutes renders even hourly rotation insufficient as a standalone control. Finally, tool access control (Q4) requires dual-layer enforcement combining discovery-time filtering (constraining `tools/list` responses) with call-time authorization checks, ideally backed by an externalized policy engine (OPA, Cerbos) operating in deny-by-default mode. A notable cross-cutting theme is that traditional RBAC is insufficient for agent systems; the emerging consensus calls for hybrid RBAC+ABAC models with context-aware, task-scoped permissions enforced via centralized policy decision points. There is broad agreement across sources that security controls must be layered -- no single mechanism (rotation, scoping, filtering, or proxy isolation) is adequate alone.

---

## Deeper Dive

### Subtopic A: Python MCP Gateway Implementation

#### Q5: FastMCP Proxy Primitives

**1. Core Proxy Primitives: Architecture Overview.** FastMCP (v3.x, current as of early 2026) is organized around three fundamental primitives: **Components** (Tools, Resources, Prompts), **Providers** (sources of components), and **Transforms** (middleware that modifies the component pipeline). The proxy system is built entirely on these primitives -- what was a specialized subsystem in v2 is now just "a Provider plus a Transform" [60].

A `FastMCP` server instance is itself an `AggregateProvider` that maintains an ordered collection of `(Provider, namespace)` tuples. `LocalProvider` is always registered first with an empty namespace `""`, giving locally-registered components (via `@mcp.tool`, etc.) precedence. Additional providers (including `ProxyProvider`) are registered via `add_provider()` with optional namespace prefixes [61].

**2. ProxyProvider Internals.** `ProxyProvider` extends `Provider` and proxies component discovery and execution to a remote MCP server via a **client factory** callable. Its constructor takes two parameters [62]:

```python
class ProxyProvider(Provider):
    def __init__(
        self,
        client_factory: ClientFactoryT,
        cache_ttl: float | None = None,  # default 300s
    ):
```

**`ClientFactoryT`** is typed as `Callable[[], Client] | Callable[[], Awaitable[Client]]` -- it can be sync or async. Every proxy component calls `_get_client()` which invokes the factory and awaits the result if it is a coroutine [62].

**Caching**: `ProxyProvider` maintains per-component-type cache entries (`_tools_cache`, `_resources_cache`, etc.) with TTL-based freshness. `_list_tools()` populates the cache; `_get_tool(name)` checks freshness before re-listing. Default TTL is 300 seconds [62].

**List/Get flow**: For `_list_tools()`, the provider creates a fresh client via factory, opens a session (`async with client:`), calls `client.list_tools()`, wraps each `mcp.types.Tool` into a `ProxyTool` via `ProxyTool.from_mcp_tool(self.client_factory, t)`, and caches the result. The `McpError` with `METHOD_NOT_FOUND` code is gracefully handled by returning an empty list [62].

**3. Proxy Component Classes (ProxyTool, ProxyResource, ProxyPrompt, ProxyTemplate).** Each proxy component class extends its base type and embeds a `_client_factory` plus a `_backend_name` / `_backend_uri` field. The key design: **each component independently manages its own client session**, which is critical for namespace transforms that rename components after creation [62].

**ProxyTool.run()** flow:
1. Resolves backend name (original name before namespace transform, via `_backend_name`)
2. Opens a tracing span
3. Calls `_get_client()` to get a fresh `Client`
4. Opens the client session (`async with client:`)
5. Forwards `call_tool_mcp(name=backend_name, arguments=arguments, meta=meta)` to the upstream
6. Propagates task metadata and experimental fields from the request context
7. Wraps the result in `ToolResult` or raises `ToolError` on error [62]

**`model_copy()` override**: Each proxy class overrides `model_copy()` to preserve the `_backend_name` / `_backend_uri` when namespace transforms rename the component. This is how namespace prefixing works without breaking upstream routing -- the proxy calls the upstream with the *original* name while the gateway exposes the *prefixed* name [62].

**4. Client Factory and Session Isolation.** The `_create_client_factory()` internal function handles multiple target types (URL strings, `Client` instances, `FastMCP` servers, `Path` objects, `MCPConfig` dicts). Session isolation strategy depends on the input [62]:

- **Already-connected `ProxyClient`**: Creates a `fresh_client_factory` via `client.new()` -- each request gets an isolated session to "avoid request context leakage"
- **Already-connected generic `Client`**: Reuses the session (warns about "context mixing in concurrent scenarios")
- **Disconnected client or other target**: Creates a `ProxyClient` base and returns `base_client.new()` for each call

**`StatefulProxyClient`** provides per-`ServerSession` caching -- it maintains a `_caches: dict[ServerSession, Client]` map, creating new upstream clients on first access per session and cleaning them up via session exit stack callbacks. This is the mechanism for session-affine proxying [62].

**5. `create_proxy()` and `FastMCPProxy`.** `create_proxy()` is the public convenience function that accepts URLs, file paths, transports, or config dicts and returns a `FastMCPProxy` instance. `FastMCPProxy` extends `FastMCP` and simply adds a `ProxyProvider` to itself [63]:

```python
class FastMCPProxy(FastMCP):
    def __init__(self, *, client_factory: ClientFactoryT, **kwargs):
        super().__init__(**kwargs)
        provider = ProxyProvider(client_factory)
        self.add_provider(provider)
```

For config-based multi-server proxying, `FastMCP.as_proxy(config)` accepts an `mcpServers` dict and creates a unified endpoint [64].

**6. `mount()` and Namespace Prefixing.** `mount()` adds a child server (or proxy) as a provider with a Namespace transform. The Namespace transform applies prefixes consistently [61] [65]:

| Component Type | Original | With `namespace="api"` |
|---|---|---|
| Tools | `get_weather` | `api_get_weather` |
| Prompts | `summarize` | `api_summarize` |
| Resources | `resource://data/file.txt` | `resource://api/data/file.txt` |
| Templates | `resource://{id}/info` | `resource://api/{id}/info` |

The connection is **live**: add a tool to the child after mounting and it is immediately visible through the parent. Conflict resolution: the most recently mounted server takes precedence [65].

Transform pipeline order: (1) Components aggregated from all providers, (2) Provider-level namespacing applied, (3) Server-level transforms applied, (4) Results returned [61].

**7. Building a Multi-Server Aggregation Gateway.** A gateway pattern mounts multiple `create_proxy()` instances with distinct namespaces:

```python
from fastmcp import FastMCP, create_proxy

gateway = FastMCP(name="Gateway")

# Mount upstream servers with namespace isolation
gateway.mount(create_proxy("http://weather-api.internal/mcp"), namespace="weather")
gateway.mount(create_proxy("http://db-api.internal/mcp"), namespace="db")
gateway.mount(create_proxy("./local_tools.py"), namespace="local")
```

This produces tools like `weather_get_forecast`, `db_query`, `local_search` etc. Each proxy component independently routes calls back to its original upstream using the `_backend_name` mechanism [63] [65].

For JSON-config-based deployment [64]:
```python
config = {
    "mcpServers": {
        "weather": {"url": "http://weather-api.internal/mcp"},
        "database": {"command": "uvx", "args": ["db-mcp-server"]},
    }
}
mcp = FastMCP.as_proxy(config, name="Multi-Server-Gateway")
```

**8. Credential Injection Patterns.**

*Pattern A: Per-upstream bearer tokens via client factory customization.* The `Client` class accepts an `auth` parameter (string token, `BearerAuth` instance, or `httpx.Auth` subclass) and a `headers` dict on the transport. For a multi-server gateway with different credentials per upstream [66]:

```python
from fastmcp import FastMCP, Client
from fastmcp.client.auth import BearerAuth

def make_authed_proxy(url: str, token: str):
    """Client factory with per-upstream credentials."""
    def factory():
        return Client(url, auth=BearerAuth(token=token))
    return FastMCPProxy(client_factory=factory, name=f"proxy-{url}")

gateway = FastMCP(name="SecureGateway")
gateway.mount(make_authed_proxy("http://api-a/mcp", os.environ["API_A_TOKEN"]), namespace="a")
gateway.mount(make_authed_proxy("http://api-b/mcp", os.environ["API_B_TOKEN"]), namespace="b")
```

Custom headers for non-standard auth schemes work via the transport's `headers` parameter [66]:
```python
Client(url, headers={"X-API-Key": secret_key})
```

*Pattern B: Inbound credential extraction via middleware, forwarded to upstream via context state.* Use `get_http_headers()` in middleware to extract caller credentials, validate them, and inject derived context into `set_state()`. Tools (or custom proxy logic) retrieve credentials from context state [67] [68]:

```python
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_headers

class CredentialInjectionMiddleware(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        headers = get_http_headers() or {}
        metadata = json.loads(headers.get("x-metadata", "{}"))
        if not validate_token(metadata.get("token")):
            raise ToolError("Unauthorized")
        context.fastmcp_context.set_state("user_creds", metadata)
        return await call_next(context)
```

*Pattern C: Dynamic per-user credential injection in the client factory.* The client factory closure can capture per-request context to create differently-authenticated upstream connections. Combined with `StatefulProxyClient` for session affinity [62] [69]:

```python
def make_per_user_factory(base_url: str):
    async def factory():
        ctx = get_context()
        user_token = ctx.get_state("user_upstream_token")
        return Client(base_url, auth=user_token)
    return factory
```

**9. Middleware System for Gateway Cross-Cutting Concerns.** FastMCP middleware (introduced v2.9, refined in v3) provides hooks at multiple granularities [67]:

- **`on_message`**: All MCP traffic (logging, metrics)
- **`on_request`** / **`on_notification`**: Request vs fire-and-forget
- **`on_call_tool`**, **`on_read_resource`**, **`on_get_prompt`**: Operation-specific interception
- **`on_list_tools`**, **`on_list_resources`**, etc.: Component listing filtration

Middleware chains execute in registration order (first-in, first-out on request path; LIFO on response). Parent middleware runs for *all* requests; mounted server middleware only for that server's requests [67].

Key gateway middleware patterns:
- **Tag-based authorization**: Check `tool.tags` for `"requires-auth"` and validate before forwarding [67]
- **Tool visibility filtering**: `on_list_tools` returns only tools the caller is authorized to see [67]
- **Input sanitization**: Modify `context.message.arguments` before forwarding [67]
- **Response enrichment**: Add metadata to results after handler execution [67]

**10. ProxyClient and MCP Feature Forwarding.** `ProxyClient` extends `Client` and automatically configures handlers for all advanced MCP features [62]:
- **Roots** (filesystem access): `default_proxy_roots_handler`
- **Sampling** (LLM completion requests): `default_proxy_sampling_handler`
- **Elicitation** (user input): `default_proxy_elicitation_handler`
- **Logging**: `default_proxy_log_handler`
- **Progress notifications**: `default_proxy_progress_handler`

These handlers forward the respective MCP protocol features bidirectionally between the downstream client and the upstream server, making the proxy transparent for advanced interactions.

**11. Performance and Operational Considerations.**
- Proxied operations add 200-500ms latency per hop for HTTP transports [63]
- Namespace depth compounds latency (nested mounts multiply round-trips)
- Cache TTL (default 300s) means component list changes on upstream servers may take up to 5 minutes to propagate
- Tool overload warning: bundling too many servers can overwhelm LLM context with tool descriptions [64]
- Authentication applies only to HTTP/SSE transports; STDIO inherits local execution security [70]

**Q5 References:**

[60] Jared Lowin. "What's New in FastMCP 3.0." *jlowin.dev*. 2025. URL: https://www.jlowin.dev/blog/fastmcp-3-whats-new. Accessed: 2026-03-27.

[61] DeepWiki. "AggregateProvider and Component Namespacing | jlowin/fastmcp." *deepwiki.com*. 2025. URL: https://deepwiki.com/jlowin/fastmcp/4.3-token-management-and-verification. Accessed: 2026-03-27.

[62] PrefectHQ/fastmcp. "src/fastmcp/server/providers/proxy.py." *GitHub*. 2025. URL: https://github.com/jlowin/fastmcp/blob/main/src/fastmcp/server/providers/proxy.py. Accessed: 2026-03-27.

[63] Jared Lowin. "MCP Proxy Servers with FastMCP 2.0." *jlowin.dev*. 2025. URL: https://www.jlowin.dev/blog/fastmcp-proxy. Accessed: 2026-03-27.

[64] Alex Retana. "Streamlining MCP Management: Bundle Multiple Servers with FastMCP Proxies." *DEV Community*. 2025. URL: https://dev.to/alexretana/streamlining-mcp-management-bundle-multiple-servers-with-fastmcp-proxies-n3i. Accessed: 2026-03-27.

[65] FastMCP. "Composing Servers." *gofastmcp.com*. 2025. URL: https://gofastmcp.com/servers/composition. Accessed: 2026-03-27.

[66] FastMCP. "Bearer Token Authentication." *gofastmcp.com*. 2025. URL: https://gofastmcp.com/clients/auth/bearer. Accessed: 2026-03-27.

[67] FastMCP. "Middleware." *gofastmcp.com*. 2025. URL: https://gofastmcp.com/servers/middleware. Accessed: 2026-03-27.

[68] Manu Francis. "Your AI Agent is Leaking Secrets to LLMs When Calling MCP Tools: Fix It with Secure Context Passing." *Medium*. 2025. URL: https://medium.com/@manuedavakandam/your-ai-agent-is-leaking-secrets-to-llms-when-calling-mcp-tools-fix-it-with-secure-context-passing-0da1ce072cd3. Accessed: 2026-03-27.

[69] Amartya Dev. "Building a Dynamic MCP Proxy Server in Python." *DEV Community*. 2025. URL: https://dev.to/amartyadev/building-a-dynamic-mcp-proxy-server-in-python-16jf. Accessed: 2026-03-27.

[70] FastMCP. "Authentication." *gofastmcp.com*. 2025. URL: https://gofastmcp.com/servers/auth/authentication. Accessed: 2026-03-27.

[71] Jared Lowin. "MCP-Native Middleware with FastMCP 2.9." *jlowin.dev*. 2025. URL: https://www.jlowin.dev/blog/fastmcp-2-9-middleware. Accessed: 2026-03-27.

[72] FastMCP. "MCP Proxy Provider." *gofastmcp.com*. 2025. URL: https://gofastmcp.com/servers/providers/proxy. Accessed: 2026-03-27.

[73] Jared Lowin. "Introducing FastMCP 3.0." *jlowin.dev*. 2025. URL: https://www.jlowin.dev/blog/fastmcp-3. Accessed: 2026-03-27.

---

#### Q6: IBM ContextForge Architecture

**1. FastAPI Application Structure.** ContextForge is a production-grade MCP gateway built on FastAPI (async web framework) with Python 3.11--3.13, deployed via Uvicorn (dev) or Gunicorn (production) ASGI servers [74]. The core codebase (~150K lines in `mcp-contextforge-gateway-core`) follows a layered architecture [75]:

```
mcpgateway/
  main.py          # FastAPI entry point
  cli.py           # CLI interface
  config.py        # Pydantic Settings (env-based config)
  models.py        # SQLAlchemy 2.0 ORM definitions
  schemas.py       # Pydantic 2.11+ validation schemas
  services/        # Business logic (ToolService, ServerService, GatewayService, A2AService, AuthService)
  transports/      # Protocol implementations (SSE, WS, stdio, streamable-HTTP)
  plugins/         # 40+ plugins for transport/protocol extensions
  validation/      # Input validation
  utils/           # JWT token gen, admin utilities
  templates/       # Jinja2 (Admin UI: HTMX + Alpine.js)
  static/          # Static assets
  translate/       # REST/gRPC-to-MCP protocol bridge
  wrapper/         # Stdio gateway wrapper for MCP clients
```

The service layer separates concerns: `ToolService` (tool registry + invocation), `ServerService` (virtual server composition), `GatewayService` (federation + peer discovery), `A2AService` (agent-to-agent), `AuthService` (JWT auth/authz) -- all operating "independently with unified auth/session/context layers" [74]. Pydantic V2 with Rust core provides 5--50x validation speed improvement over V1, and `orjson` (Rust-powered) delivers 5--6x faster JSON serialization [74].

**2. Async Patterns and the "Fetch-Then-Release" DB Pattern.** Full async/await throughout, using SQLAlchemy 2.0 async ORM. The most instructive pattern discovered via a production bug (Issue #1706): under 1,000 concurrent users, **65% of DB connections were stuck idle-in-transaction** while waiting for upstream MCP server HTTP responses [76].

The root cause: `invoke_tool()` held a DB session across the entire request lifecycle, including the network call to upstream MCP servers (100ms--4+ minutes). The fix introduced a **"Fetch-Then-Release" pattern** [76]:

1. **Eager-load with `joinedload()`** -- fetch tool + gateway relationship in a single query
2. **Copy to local variables** -- extract all needed fields (id, name, url, auth_type, etc.)
3. **`expunge()` + `close()`** -- detach ORM objects and release the connection before network I/O
4. **Network operations** -- perform upstream HTTP calls with no DB session held
5. **Fresh session for metrics** -- use `@asynccontextmanager` to get an isolated session for write-back

This dropped connection hold time from 100ms--4min to <50ms, increasing max concurrent requests from ~200 to ~3,000+ [76].

**Lesson for CommandClaw**: Any MCP gateway that proxies tool calls must decouple DB sessions from upstream network I/O. The `expunge()` + fresh-session pattern is the canonical SQLAlchemy approach.

**3. Session Pooling (MCP Client Sessions).** Introduced in v1.0.0-BETA-1 (Dec 2025), MCP client session pooling enables connection reuse to upstream MCP servers, delivering **10--20x latency reduction** [77][80]. Key configuration parameters:

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `MCP_SESSION_POOL_ENABLED` | false | Master toggle |
| `MCP_SESSION_POOL_MAX_PER_KEY` | 10 | Max sessions per (URL, identity_hash, transport_type) tuple |
| `MCP_SESSION_POOL_TTL` | 300s | Session time-to-live before forced closure |
| `MCP_SESSION_POOL_HEALTH_CHECK_INTERVAL` | 60s | Idle time before validation |
| `MCP_SESSION_POOL_ACQUIRE_TIMEOUT` | 30s | Max wait to acquire a session |
| `MCP_SESSION_POOL_CREATE_TIMEOUT` | 30s | Max wait to create a new session |
| `MCP_SESSION_POOL_IDLE_EVICTION` | 600s | Idle keys evicted after this duration |
| `MCP_SESSION_POOL_TRANSPORT_TIMEOUT` | 30s | Applies to all HTTP ops on pooled sessions |

The pool key is `(URL, identity_hash, transport_type)`, ensuring **different users never share sessions** [78]. An integrated circuit breaker protects the pool: after `MCP_SESSION_POOL_CIRCUIT_BREAKER_THRESHOLD` (default: 5) failures, the circuit opens for `CIRCUIT_BREAKER_RESET` (default: 60s) before entering half-open state [77][78].

Optional explicit health check RPC (`MCP_SESSION_POOL_EXPLICIT_HEALTH_RPC=true`) adds ~5ms latency per check for stricter validation [78].

**Lesson**: Pool keying by (URL, identity, transport) is critical for multi-tenant security. The circuit breaker integration at the pool level prevents cascading failures when upstream servers degrade.

**4. Transport Bridging and Protocol Translation.** The gateway implements a **Transport Router** that handles protocol conversion across HTTP, JSON-RPC, SSE (with configurable keepalive), WebSocket, stdio, and streamable-HTTP [74]. Key transport components:

- **`mcpgateway.translate`** -- CLI tool that wraps any stdio-only MCP server and exposes it over SSE: `python3 -m mcpgateway.translate --stdio "uvx mcp-server-git" --expose-sse --port 8001` [79]
- **`mcpgateway.wrapper`** -- Stdio gateway wrapper enabling MCP clients that only speak stdio to connect to the HTTP-based gateway [81]
- **gRPC-to-MCP translation** (v1.0.0-BETA-1) -- zero-configuration gRPC service discovery with automatic protocol translation and TLS/mTLS support [80]
- **REST-to-MCP adapter** -- wraps arbitrary REST APIs as virtual MCP-compliant tools [74]

Transport-specific settings: `WEBSOCKET_PING_INTERVAL=30s`, `SSE_RETRY_TIMEOUT=5000ms`. An experimental Rust MCP runtime sidecar (`experimental_rust_mcp_runtime_enabled`) can be enabled for high-throughput scenarios [77].

The architecture stores active transports by session ID, generating unique identifiers and maintaining transport references for future requests. The `TRANSPORT_TYPE` env var selects the protocol mode (`http`, `ws`, `sse`, `stdio`, `all`) [77].

**Lesson**: The translate bridge pattern (stdio-to-SSE) is the most reusable design -- it solves the extremely common problem of connecting modern HTTP-based gateways to stdio-only MCP servers without modifying them.

**5. Database Schema and Connection Management.** SQLAlchemy 2.0 ORM with 36--55+ tables (varies by version) across PostgreSQL (production), SQLite (development), and MySQL/MariaDB [74][77]. Alembic handles schema migrations with auto-generation [75].

Connection pool configuration [77]:

| Parameter | Default | Notes |
|-----------|---------|-------|
| `DB_POOL_SIZE` | 200 | Base connections |
| `DB_MAX_OVERFLOW` | 10 | Burst beyond pool_size |
| `DB_POOL_TIMEOUT` | 30s | Wait threshold |
| `DB_POOL_RECYCLE` | 3600s | Connection refresh interval |
| `DB_POOL_CLASS` | auto | Options: auto, null, queue |
| `DB_POOL_PRE_PING` | auto | Connection health check before reuse |

Session injection uses FastAPI's `Depends(get_db)` pattern [75]. In v1.0.0-BETA-2, they migrated from psycopg2 to psycopg3 for improved async support and added PgBouncer integration that reduced DB connections by ~50% [80].

Resilience: `DB_MAX_RETRIES=30`, `DB_RETRY_INTERVAL_MS=2000`, `DB_MAX_BACKOFF_SECONDS=30` for startup retry with exponential backoff [77].

Key ORM entities (inferred from Issue #1706): `DbTool` (with `gateway` relationship via `joinedload`), `DbGateway` (URL, auth_type, ca_certificate), `GlobalConfig` (passthrough headers) [76].

**6. OpenTelemetry Integration.** Vendor-agnostic OTLP tracing with support for Phoenix, Jaeger, Zipkin, Tempo, DataDog, New Relic [74][82]. Configuration:

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `OTEL_ENABLE_OBSERVABILITY` | false | Master toggle |
| `OTEL_TRACES_EXPORTER` | otlp | Options: otlp, jaeger, zipkin, console |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | localhost:4317 | gRPC collector endpoint |
| `OTEL_TRACES_SAMPLER_ARG` | 0.1 | 10% default sampling rate |
| `OTEL_BSP_MAX_QUEUE_SIZE` | 2048 | Batch span processor queue |
| `OBSERVABILITY_TRACE_RETENTION_DAYS` | 7 | Trace retention window |

In addition to OTLP export, v0.9.0 introduced an **internal observability platform** with self-contained tracing, Gantt charts, and flame graphs -- zero-overhead when disabled [80]. The internal platform tracks:
- `observability_trace_http_requests` (default: true)
- `observability_sample_rate` (default: 1.0 for internal)
- `observability_max_traces` (default: 100,000)
- `observability_metrics_enabled` / `observability_events_enabled`
- `DB_METRICS_RECORDING_ENABLED` for database-level metrics [77]

Prometheus-compatible metrics are exported for circuit breaker state, state transitions, failure counters, and trial request outcomes [83].

**Lesson**: The dual observability approach (internal self-contained + external OTLP) is pragmatic. The internal system provides immediate value without infrastructure, while OTLP integrates with existing enterprise monitoring.

**7. Credential Encryption at Rest.** Credentials stored in the database are encrypted using **Fernet (AES-128-CBC + HMAC-SHA256)** with **Argon2id key derivation** (not PBKDF2) [84][77]:

- Master key: `AUTH_ENCRYPTION_SECRET` (minimum 32 characters, entropy validation)
- Argon2id parameters: `time_cost=3`, `memory_cost=65536 KB (64 MB)`, `parallelism=1`, `hash_length=32 bytes`, `salt_length=16 bytes`
- Encrypted format: JSON bundle `{"kdf":"argon2id","t":3,"m":65536,"p":1,"salt":"<base64>","token":"gAAAAA..."}`
- Functions: `encrypt_secret()` / `decrypt_secret()` on an encryption service with `encryption_secret` constructor parameter
- Legacy support: transparent decryption of older PBKDF2 base64-wrapped Fernet tokens [84]

Password hashing (for user accounts) uses Argon2id separately with the standard `$argon2id$v=19$m=65536,t=3,p=1$<salt>$<hash>` output format [74].

JWT configuration supports HS256, RS256, ES256 with configurable key paths, audience/issuer verification, JTI requirement (mandatory since v1.0.0-RC1), and environment embedding [77][80].

**Lesson**: The per-secret unique salt embedded in the JSON bundle alongside KDF parameters is a strong pattern -- it makes the encryption self-describing and supports algorithm migration without breaking existing ciphertext.

**8. Additional Architectural Highlights.**
- **Multi-tier caching**: L1 in-memory + L2 Redis (`TOOL_LOOKUP_CACHE_TTL_SECONDS=60`), with `CACHE_TYPE` options of `none`, `memory`, `database`, `redis` [77]
- **Response compression**: Brotli, Zstd, GZip with 30--70% bandwidth reduction (v0.9.0) [80]
- **SSRF protection**: Strict by default since v1.0.0-RC2, blocking localhost and private networks, with CIDR allowlists [77][80]
- **Rust acceleration**: Plugin-level Rust modules for PII filtering (5--100x faster than Python), experimental Rust MCP runtime sidecar [80]
- **Redis leader election**: `REDIS_LEADER_TTL=15s`, `REDIS_LEADER_HEARTBEAT_INTERVAL=5s` for multi-instance coordination [77]
- **TOON compression**: Custom tool output optimization reducing payload sizes for agent consumption [79]

**Q6 References:**

[74] IBM. "Overview -- Architecture." *ContextForge AI Gateway Documentation*. 2025. URL: https://ibm.github.io/mcp-context-forge/architecture/. Accessed: 2026-03-27.

[75] IBM. "DEVELOPING.md." *GitHub: IBM/mcp-context-forge*. 2025. URL: https://github.com/IBM/mcp-context-forge/blob/main/DEVELOPING.md. Accessed: 2026-03-27.

[76] IBM. "[BUG][DB]: Connection pool exhaustion -- sessions held during upstream HTTP calls. Issue #1706." *GitHub: IBM/mcp-context-forge*. 2025. URL: https://github.com/IBM/mcp-context-forge/issues/1706. Accessed: 2026-03-27.

[77] IBM. ".env.example and Configuration Reference." *ContextForge AI Gateway Documentation*. 2025. URL: https://ibm.github.io/mcp-context-forge/manage/configuration/. Accessed: 2026-03-27.

[78] IBM. "config.py -- MCP Session Pool Settings." *GitHub: IBM/mcp-context-forge*. 2025. URL: https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/config.py. Accessed: 2026-03-27.

[79] IBM. "README.md." *GitHub: IBM/mcp-context-forge*. 2025. URL: https://github.com/IBM/mcp-context-forge. Accessed: 2026-03-27.

[80] IBM. "Releases." *GitHub: IBM/mcp-context-forge*. 2025--2026. URL: https://github.com/IBM/mcp-context-forge/releases. Accessed: 2026-03-27.

[81] "mcp-contextforge-gateway." *PyPI*. December 16, 2025. URL: https://pypi.org/project/mcp-contextforge-gateway/. Accessed: 2026-03-27.

[82] IBM. "Observability." *ContextForge AI Gateway Documentation*. 2025. URL: https://ibm.github.io/mcp-context-forge/manage/observability/. Accessed: 2026-03-27.

[83] IBM. "[FEATURE]: Full circuit breakers for unstable MCP server backends. Issue #301." *GitHub: IBM/mcp-context-forge*. 2025. URL: https://github.com/IBM/mcp-context-forge/issues/301. Accessed: 2026-03-27.

[84] IBM. "[TESTING][SECURITY]: Encryption and secrets manual test plan (Argon2, Fernet, key derivation). Issue #2405." *GitHub: IBM/mcp-context-forge*. 2026. URL: https://github.com/IBM/mcp-context-forge/issues/2405. Accessed: 2026-03-27.

[85] Alain Airom. "Forge Your Context: Orchestrating the ContextForge MCP Gateway with IBM Project Bob." *DEV Community*. 2025. URL: https://dev.to/aairom/forge-your-context-orchestrating-the-contextforge-mcp-gateway-with-ibm-project-bob-3p75. Accessed: 2026-03-27.

---

### Subtopic B: Phantom Token + Key Rotation Implementation

#### Q7: Phantom Token Pattern for MCP

**1. The Phantom Token Pattern: Core Architecture.** The phantom token pattern originates from Curity's OAuth security model and splits authentication into two layers: an **opaque reference token** visible to clients (or agents), and a **real credential** (JWT or API key) known only to the gateway/proxy [86][87]. The agent never sees the real credential. When a request arrives at the proxy, it validates the opaque token, strips it, retrieves the real credential from a secure store, injects it, and forwards to the upstream API [88].

For MCP gateways specifically, the pattern maps directly: the MCP client (agent) receives a meaningless session token; the MCP gateway intercepts tool calls, validates the phantom token, and injects scoped real credentials before forwarding to upstream APIs [89][90].

**2. Token Generation: `secrets.token_urlsafe` vs HMAC-Derived.** There are two distinct token-generation strategies, each serving a different purpose:

**Opaque session tokens** (what agents receive): Use `secrets.token_urlsafe(32)` or `secrets.token_hex(32)` to produce 256-bit cryptographically random strings. These are pure random references with no embedded meaning -- they serve as lookup keys into a server-side credential map [91][88]. The nono credential proxy generates "a cryptographically random 256-bit session token (32 bytes, hex-encoded to 64 characters)" per session [88].

```python
import secrets
phantom_token = secrets.token_urlsafe(32)  # 256-bit, URL-safe base64
# or
phantom_token = secrets.token_hex(32)      # 256-bit, hex-encoded (64 chars)
```

**HMAC-signed request tokens** (for request integrity): HMAC is not used to *generate* the opaque token itself -- it is used to *sign individual requests* so the proxy can verify that the request came from a legitimate holder of the session key and was not tampered with in transit. The canonical string typically includes method, path, timestamp, nonce, and body hash [92][93]:

```python
import hmac, hashlib, base64

def sign_request(session_token: str, method: str, path: str,
                 timestamp: str, nonce: str, body: bytes) -> str:
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = '\n'.join([
        method.upper(), path, timestamp, nonce, body_hash
    ])
    signature = hmac.new(
        session_token.encode('utf-8'),
        canonical.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(signature).decode('utf-8')
```

The session token doubles as the HMAC key -- meaning only the agent holding the correct phantom token can produce valid signatures. The proxy, which also stores the phantom token, recomputes and verifies using `hmac.compare_digest()` for constant-time comparison [92][93].

**3. HMAC Request Verification in the Proxy.** A production FastAPI proxy dependency for verifying HMAC-signed requests [92]:

```python
import hmac, hashlib, time
from collections import OrderedDict
from fastapi import Request, HTTPException, Depends
from fastapi.security import APIKeyHeader

TIMESTAMP_TOLERANCE = 300  # 5 minutes

class NonceCache:
    def __init__(self, max_size: int = 10000):
        self._cache: OrderedDict[str, float] = OrderedDict()
        self._max_size = max_size

    def check_and_add(self, nonce: str) -> bool:
        cutoff = time.time() - TIMESTAMP_TOLERANCE
        while self._cache and next(iter(self._cache.values())) < cutoff:
            self._cache.popitem(last=False)
        if nonce in self._cache:
            return False  # replay detected
        self._cache[nonce] = time.time()
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
        return True

nonce_cache = NonceCache()

async def verify_hmac(request: Request,
                      x_token: str = Depends(APIKeyHeader(name="X-Phantom-Token")),
                      x_timestamp: str = Depends(APIKeyHeader(name="X-Timestamp")),
                      x_signature: str = Depends(APIKeyHeader(name="X-Signature")),
                      x_nonce: str = Depends(APIKeyHeader(name="X-Nonce"))):
    # 1. Timestamp freshness check
    req_time = float(x_timestamp)
    if abs(time.time() - req_time) > TIMESTAMP_TOLERANCE:
        raise HTTPException(401, "Request timestamp outside tolerance window")

    # 2. Replay detection
    if not nonce_cache.check_and_add(x_nonce):
        raise HTTPException(401, "Nonce reuse detected")

    # 3. Lookup session token (the phantom token IS the HMAC key)
    session = token_store.get(x_token)
    if not session:
        raise HTTPException(401, "Invalid phantom token")

    # 4. Recompute signature
    body = await request.body()
    canonical = build_canonical(request.method, request.url.path,
                                x_timestamp, x_nonce, body)
    expected = hmac.new(session.hmac_key.encode(), canonical.encode(),
                        hashlib.sha256).hexdigest()

    # 5. Constant-time comparison
    if not hmac.compare_digest(expected, x_signature):
        raise HTTPException(401, "Invalid signature")

    return session
```

Key security considerations: sign a "canonical string" that includes host, method, path, timestamp, and body -- not just the body alone. Reject timestamps outside a 5-minute window. Use nonce tracking to prevent replay attacks [93][92].

**4. Token-to-Credential Lookup.** The proxy maintains a mapping from phantom tokens to real credentials. The nono design uses a trait/interface pattern with pluggable backends [94]:

```python
from dataclasses import dataclass, field
from typing import Optional, Dict, Protocol
import time

class CredentialBackend(Protocol):
    def load(self, account: str) -> str: ...

@dataclass
class CredentialEntry:
    real_credential: str
    upstream_url: str
    header_name: str = "Authorization"
    credential_format: str = "Bearer {}"
    expires_at: Optional[float] = None

    def is_expired(self) -> bool:
        return self.expires_at is not None and time.time() >= self.expires_at

@dataclass
class PhantomSession:
    phantom_token: str
    hmac_key: str           # can be same as phantom_token or separate
    credentials: Dict[str, CredentialEntry] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0

class TokenStore:
    def __init__(self):
        self._sessions: Dict[str, PhantomSession] = {}
        self._prev_sessions: Dict[str, PhantomSession] = {}  # overlap window

    def get(self, phantom_token: str) -> Optional[PhantomSession]:
        """Check current tokens first, then previous (overlap window)."""
        session = self._sessions.get(phantom_token)
        if session and not self._is_session_expired(session):
            return session
        # Fall back to previous generation during overlap
        session = self._prev_sessions.get(phantom_token)
        if session and not self._is_session_expired(session):
            return session
        return None
```

The nono proxy supports four credential injection modes: header injection (default, e.g., `Authorization: Bearer {real_key}`), query parameter injection, Basic Auth (base64 encoding), and custom path-based injection [88]. Credential backends include system keyring, HashiCorp Vault, AWS Secrets Manager, and environment variables [94].

**5. Dual-Key Overlap Window for Rotation.** The overlap window is the critical mechanism that enables zero-downtime rotation. The pattern works as follows [95][96][97]:

**Rotation lifecycle with 5-minute overlap:**

```
T=0:00  Token A active (current generation)
T=0:55  Rotation triggered: generate Token B
T=0:55  Token B becomes "current"; Token A moves to "previous"
T=0:55  Both A and B are valid (overlap window begins)
T=1:00  Token A expires (overlap window ends after 5 minutes)
T=1:00  Only Token B is valid
T=1:55  Next rotation: generate Token C, Token B -> previous...
```

Implementation pattern for the dual-key store:

```python
import secrets
import time
import threading

class RotatingTokenManager:
    def __init__(self, rotation_interval: int = 3600, overlap_window: int = 300):
        self.rotation_interval = rotation_interval  # e.g., 1 hour
        self.overlap_window = overlap_window          # e.g., 5 minutes
        self._lock = threading.Lock()
        self._current_token: str = ""
        self._current_created: float = 0
        self._previous_token: Optional[str] = None
        self._previous_expires: float = 0
        self._credentials: Dict[str, CredentialEntry] = {}
        self._rotate()  # initial token

    def _rotate(self):
        with self._lock:
            if self._current_token:
                self._previous_token = self._current_token
                self._previous_expires = time.time() + self.overlap_window
            self._current_token = secrets.token_urlsafe(32)
            self._current_created = time.time()

    def validate(self, token: str) -> bool:
        with self._lock:
            if hmac.compare_digest(token, self._current_token):
                return True
            if (self._previous_token and
                time.time() < self._previous_expires and
                hmac.compare_digest(token, self._previous_token)):
                return True
            return False

    def get_current_token(self) -> str:
        """Distribute to agents."""
        with self._lock:
            return self._current_token

    def maybe_rotate(self):
        if time.time() - self._current_created >= self.rotation_interval:
            self._rotate()
```

The Azure Key Vault dual-credential rotation tutorial formalizes this as an alternating primary/secondary key strategy: when one key is stored as the latest version, the alternate key is regenerated and published as the new latest, providing an "entire rotation cycle" with continuous availability [95].

**6. Distributing Rotated Tokens to Agents.** For MCP agents, token distribution can follow several patterns:

*Environment variable injection at session start*: The proxy spawns the agent with `OPENAI_API_KEY=<phantom_token>` and `OPENAI_BASE_URL=http://127.0.0.1:<port>/openai`. Standard LLM SDKs respect these base URL overrides and automatically route through the proxy [88][89].

*Session creation endpoint*: More flexible for long-running agents. The orchestrator calls `POST /proxy/sessions` to receive a new phantom token, then passes it to the agent. Sessions auto-expire (default 1 hour, max 24 hours) [88].

*Push notification on rotation*: For agents that survive across rotation boundaries, the proxy can notify via a control channel (SSE stream or webhook) that a new token is available. The agent fetches the new token from a well-known endpoint:

```python
# Agent-side token refresh (simplified)
async def token_refresh_loop(proxy_url: str, current_token: str):
    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(
                f"{proxy_url}/.well-known/token",
                headers={"X-Phantom-Token": current_token}
            )
            if resp.status_code == 200:
                new_token = resp.json()["token"]
                if new_token != current_token:
                    current_token = new_token
                    update_sdk_token(current_token)
            await asyncio.sleep(30)  # poll interval
```

The overlap window ensures that agents using the old token during the polling interval are not rejected [96].

**7. Revocation Mechanics.** Revocation operates at multiple levels:

*Immediate session revocation*: Delete the phantom token from the token store. Any subsequent request with that token fails validation immediately [88]. The nono proxy supports `SIGINT` to revoke the session immediately.

*Credential-level revocation*: Remove or rotate the real credential in the backend vault. The proxy's next credential fetch returns the updated value; agents are unaffected because they only hold phantom tokens [94].

*Token family revocation* (for replay detection): If a revoked token is reused, the entire token family can be invalidated, forcing re-authentication. This mirrors OAuth refresh token rotation replay detection [98].

*Deny-list approach*: For distributed proxies, maintain a short-lived deny-list (backed by Redis or similar) of revoked token hashes. Check the deny-list during validation before performing the credential lookup.

**8. MCP-Specific Gateway Architecture.** The recommended MCP gateway pattern (Pattern 5 from Solo.io) offloads credential handling entirely from both the MCP client and MCP server into dedicated gateway infrastructure [90][99]:

```
Agent (MCP Client) --[phantom token]--> MCP Gateway --[real credential]--> Upstream API
                                            |
                                     Token Store + Vault
```

The Red Hat MCP Gateway implementation demonstrates three credential injection strategies within the gateway [100]:
1. **Signed wristband headers**: ES256-signed JWTs injected as `x-authorized-tools` headers with 300-second TTL
2. **OAuth 2.1 token exchange (RFC 8693)**: Broad-scope agent token exchanged for narrow-scope upstream token per MCP server
3. **HashiCorp Vault per-user lookup**: For non-OAuth APIs, credentials fetched from Vault indexed by user identity and target host

**9. Full Proxy Pipeline Summary.** The complete request lifecycle in a phantom-token MCP gateway:

1. Agent sends request with phantom token in `Authorization` header (or `X-Phantom-Token`) to `http://localhost:<port>/<service>/...`
2. Proxy extracts phantom token and HMAC signature headers
3. Timestamp freshness check (reject if >5 min drift)
4. Nonce uniqueness check (reject replays)
5. Token lookup in current generation, then previous generation (overlap window)
6. HMAC signature verification using phantom token as key (constant-time comparison)
7. Service prefix extraction from URL path determines which credential entry to use
8. Real credential fetched from backend (keyring/Vault/secrets manager); refreshed if TTL expired
9. Phantom token and HMAC headers stripped from request
10. Real credential injected in configured format (`Authorization: Bearer ...`, query param, etc.)
11. Request forwarded to upstream over TLS
12. Response streamed back to agent without buffering (supports SSE/chunked)
13. Audit log entry written (no sensitive data logged -- headers, bodies, query params excluded) [88][94]

**10. Security Hardening Considerations.**
- **Constant-time comparison**: Always use `hmac.compare_digest()` -- standard `==` leaks timing information [92][93]
- **Memory protection**: Real credentials should be zeroed on deallocation. In Python, this is harder than Rust's `Zeroizing<String>`, but you can use `ctypes.memset` on bytearrays or store credentials in `mmap`-backed buffers that can be explicitly wiped [88]
- **DNS rebinding protection**: Resolve hostnames once, check all resolved IPs against a deny CIDR list, connect using pre-resolved addresses [88][101]
- **Bind to loopback only**: The proxy binds to `127.0.0.1:0` (ephemeral port), requiring both the random port AND the phantom token for access [94]
- **MCP spec mandates**: Tokens must be audience-bound (resource indicators), token passthrough is forbidden, and MCP servers must not accept tokens not explicitly issued for them [101]

**Q7 References:**

[86] Nordic APIs. "Understanding The Phantom Token Approach." *Nordic APIs*. URL: https://nordicapis.com/understanding-the-phantom-token-approach/. Accessed: 2026-03-27.

[87] Curity. "Securing APIs with The Phantom Token Approach." *Curity*. URL: https://curity.io/resources/learn/phantom-token-pattern/. Accessed: 2026-03-27.

[88] nono. "Credential Protection for AI Agents: The Phantom Token Pattern." *nono.sh*. URL: https://nono.sh/blog/blog-credential-injection. Accessed: 2026-03-27.

[89] API Stronghold. "The Phantom Token Pattern, but for Production AI Agents." *API Stronghold*. URL: https://www.apistronghold.com/blog/phantom-token-pattern-production-ai-agents. Accessed: 2026-03-27.

[90] Solo.io. "MCP Authorization Patterns for Upstream API Calls." *Solo.io*. URL: https://www.solo.io/blog/mcp-authorization-patterns-for-upstream-api-calls. Accessed: 2026-03-27.

[91] Python Software Foundation. "secrets -- Generate secure random numbers for managing secrets." *Python Docs*. URL: https://docs.python.org/3/library/secrets.html. Accessed: 2026-03-27.

[92] OneUptime. "How to Secure APIs with HMAC Signing in Python." *OneUptime Blog*. 2026-01-22. URL: https://oneuptime.com/blog/post/2026-01-22-hmac-signing-python-api/view. Accessed: 2026-03-27.

[93] GitGuardian. "HMAC Secrets Explained: Authentication You Can Actually Implement." *GitGuardian Blog*. URL: https://blog.gitguardian.com/hmac-secrets-explained-authentication/. Accessed: 2026-03-27.

[94] Luke Hinds. "nono-networking-credential-design.md." *GitHub Gist*. URL: https://gist.github.com/lukehinds/9346514519b5c7a3047de5a0b0e083ae. Accessed: 2026-03-27.

[95] Microsoft. "Rotation tutorial for resources with two sets of credentials." *Microsoft Learn*. 2026-03-26. URL: https://learn.microsoft.com/en-us/azure/key-vault/secrets/tutorial-rotation-dual. Accessed: 2026-03-27.

[96] Zuplo. "API Key Rotation and Lifecycle Management: Zero-Downtime Strategies." *Zuplo*. URL: https://zuplo.com/learning-center/api-key-rotation-lifecycle-management. Accessed: 2026-03-27.

[97] OneUptime. "How to Build Token Rotation Strategies." *OneUptime Blog*. 2026-01-30. URL: https://oneuptime.com/blog/post/2026-01-30-token-rotation-strategies/view. Accessed: 2026-03-27.

[98] better-auth. "Refresh Token Rotation Grace Period (Overlap Window) -- Issue #8512." *GitHub*. URL: https://github.com/better-auth/better-auth/issues/8512. Accessed: 2026-03-27.

[99] Doppler. "MCP security best practices for credentials, tokens, and secrets." *Doppler Blog*. URL: https://www.doppler.com/blog/mcp-server-credential-security-best-practices. Accessed: 2026-03-27.

[100] Red Hat. "Advanced authentication and authorization for MCP Gateway." *Red Hat Developer*. 2025-12-12. URL: https://developers.redhat.com/articles/2025/12/12/advanced-authentication-authorization-mcp-gateway. Accessed: 2026-03-27.

[101] Model Context Protocol. "Security Best Practices." *modelcontextprotocol.io*. URL: https://modelcontextprotocol.io/specification/draft/basic/security_best_practices. Accessed: 2026-03-27.

[102] Tyler Pinho. "Phantom Token Architecture: Protecting Sensitive Data in OAuth." *tylerpinho.com*. URL: https://www.tylerpinho.com/tutorials/phantom-token-architecture. Accessed: 2026-03-27.

---

#### Q8: Envoy Token-Encoded Sessions

**1. The Problem: MCP is Stateful, Gateways Want to Be Stateless.** MCP (Model Context Protocol) is inherently stateful: a session ID must be reused across calls so servers maintain context [103]. When a gateway sits between a client and multiple upstream MCP servers (e.g., GitHub, Jira, local files), each upstream maintains its own independent session. The gateway must fan a single client session out to N upstream sessions and route subsequent requests back to the correct upstream session [104]. The conventional solutions -- sticky sessions (load-balancer affinity) or distributed session stores (Redis, DynamoDB) -- introduce operational complexity, single points of failure, or horizontal-scaling bottlenecks [108].

**2. Core Architecture: Encrypt-in-Token, Decode-on-Any-Replica.** Envoy AI Gateway solves this by encoding all upstream session routing state directly into the client-facing session ID, then encrypting it. The flow is [103][104]:

1. **Session initialization**: Client connects; gateway establishes upstream sessions with each backend MCP server.
2. **Composite session ID construction**: The gateway serializes a composite string containing the route name, authenticated subject, and per-backend entries (backend name, base64-encoded upstream session ID, capability flags). The format is:
   ```
   {routeName}@{subject}@{backend1}:{base64(upstreamSessionID1)}:{capHex1},{backend2}:{base64(upstreamSessionID2)}:{capHex2}
   ```
   Example: `some-awesome-route@mcp-user@backend1:MTIzNDU2:001,backend2:NjU0MzIx:002` [105].
3. **Encryption**: The composite string is encrypted using PBKDF2 + AES-256-GCM and returned to the client as the `Mcp-Session-Id` header value.
4. **Subsequent requests**: Any gateway replica receives the encrypted session ID, decrypts it, parses out the route and per-backend session mappings, and routes the JSON-RPC message to the correct upstream(s) -- no database lookup required [103].

**3. Cryptographic Implementation Details.** The implementation lives in `internal/mcpproxy/crypto.go` in the `envoyproxy/ai-gateway` repository [105]:

- **KDF**: PBKDF2 with SHA-256 hash function.
- **KDF parameters**: 16-byte random salt per encryption, 32-byte (256-bit) derived key, configurable iteration count (default: 100,000).
- **Cipher**: AES-256-GCM (authenticated encryption with associated data).
- **Nonce**: Random nonce per encryption via `crypto/rand`, sized to GCM's `NonceSize()` (12 bytes standard).
- **Wire format**: `base64(salt || nonce || ciphertext)` -- the salt, nonce, and GCM ciphertext+tag are concatenated then base64-encoded.
- **Constructor**: `NewPBKDF2AesGcmSessionCrypto(seed string, iterations int)` -- only the seed and iteration count are caller-configurable; salt length (16) and key length (32) are hardcoded [105].

**Key rotation** is supported via `FallbackEnabledSessionCrypto`: a secondary (previous) seed+iterations pair is tried if the primary decryption fails, enabling zero-downtime seed rotation [105][107].

**4. Session Data Structures.** The in-memory session object holds [105]:

```go
type session struct {
    id                 secureClientToGatewaySessionID      // encrypted token
    route              string
    reqCtx             *mcpRequestContext
    mu                 sync.RWMutex
    perBackendSessions map[MCPBackendName]*compositeSessionEntry
    extraHeaders       map[string]string
}
```

Each `compositeSessionEntry` contains:
- `backendName` -- identifies the upstream MCP server
- `sessionID` -- the gateway-to-upstream-server session ID
- `lastEventID` -- for SSE reconnection (`Last-Event-ID`)
- `capabilities` -- 9-bit bitmask encoded as 3-char hex, covering: Tools, ToolsListChanged, Prompts, PromptsListChanged, Logging, Resources, ResourcesListChanged, ResourcesSubscribe, Completions [105].

The subject field (authenticated user identity) is bound into the encrypted token to prevent session hijacking -- a different user cannot reuse another's session ID [105].

**5. Helm/Operational Configuration.** The default Helm values expose [107]:

```yaml
mcp:
  sessionEncryption:
    seed: "default-insecure-seed"   # MUST override in production
    iterations: 100000              # PBKDF2 iterations
    fallback:
      seed: ""                      # previous seed for rotation
      iterations: 100000
```

All replicas share the same seed, so any replica can decrypt any session token. This is the sole shared secret; no shared state store is needed [103][107].

**6. Performance Characteristics.** Benchmarked on MacBook Pro M1 (8-core) [103][106]:

| Configuration | Session-creation overhead | Notes |
|---|---|---|
| Default (100k PBKDF2 iterations) | ~tens of ms | Conservative; suitable for high-security |
| Tuned (~100 iterations) | ~1-2 ms | Comparable to other MCP gateways |

End-to-end benchmark (echo tool call) [106]:
- **No proxy baseline**: ~80 ms avg (79-82 us/op)
- **Envoy AI Gateway (100 iter)**: ~385 ms avg
- **Agent Gateway (Rust, stateful)**: ~160 ms avg
- **Delta between Envoy (tuned) and Agent Gateway**: ~0.2 ms -- "negligible in real-world scenarios"

The blog notes that MCP tool calls occur within LLM conversation turns that themselves take seconds, making sub-millisecond gateway overhead irrelevant in practice [106].

**Important**: the PBKDF2 cost is paid only on session creation (and re-establishment after reconnection), not on every single JSON-RPC message within an existing session. Once the session is active and the upstream connections are established in-process, routing uses the already-decrypted in-memory session map [105].

**7. Trade-offs vs. Distributed Session Stores.**

| Dimension | Token-Encoded (Envoy AI Gateway) | Redis/DB Session Store | Sticky Sessions |
|---|---|---|---|
| **Horizontal scaling** | Any replica handles any request; add replicas freely [103] | Requires HA Redis cluster; all replicas must reach the store | Tied to specific instance; rebalancing breaks sessions |
| **Operational complexity** | Single shared secret to distribute | Redis deployment, monitoring, backup, failover | Load-balancer affinity config; no HA for sessions |
| **Latency per request** | CPU cost of PBKDF2+AES-GCM decrypt (~1-2ms tuned, ~tens ms default) [106] | Network RTT to Redis (~0.5-2ms on local network) [108] | Zero extra latency (direct routing) |
| **Failure mode** | No SPOF; secret loss = all sessions invalid (rotate to recover) | Redis down = all sessions lost; requires cluster mode | Instance failure = sessions lost for that instance |
| **Token size** | Grows linearly with number of backends (base64 of encrypted composite); potentially large headers for many backends | Fixed-size session ID (e.g., UUID); server stores the mapping | Fixed-size session ID |
| **Security model** | Tamper-proof (AES-GCM authentication tag); subject-bound; encrypted | Server-side only; session ID is opaque reference | Server-side only |
| **Key rotation** | Supported via fallback seed [107] | N/A (session data in store) | N/A |
| **Session invalidation** | Cannot revoke individual sessions without maintaining a blocklist (a classic JWT-like limitation) | Immediate per-session invalidation via DELETE | Instance-local invalidation |

**8. Applicability to a Python MCP Gateway.** The pattern is directly portable to Python. The cryptographic primitives are available in `cryptography` (preferred) or `pycryptodome`:

- `cryptography.hazmat.primitives.kdf.pbkdf2.PBKDF2HMAC` for KDF
- `cryptography.hazmat.primitives.ciphers.aead.AESGCM` for AES-256-GCM
- Token format: `base64(salt + nonce + ciphertext)` is trivially reproducible

Considerations for a Python implementation:

- **PBKDF2 performance**: Python's `hashlib.pbkdf2_hmac` is C-accelerated and performs comparably to Go for the same iteration count. At 100 iterations, overhead is sub-millisecond.
- **Async compatibility**: Encryption/decryption is CPU-bound; in an async Python gateway (e.g., FastAPI + uvicorn), offload to a thread pool via `asyncio.to_thread()` to avoid blocking the event loop.
- **Token size**: For a gateway aggregating many backends, the encrypted token can become large. HTTP header size limits (typically 8-16 KB) set an upper bound on the number of backends per session.
- **Session invalidation gap**: Like JWTs, you cannot revoke a specific token without a server-side blocklist. If immediate revocation is required, a lightweight Redis set of revoked session hashes can complement the token-encoded approach without requiring full session state in Redis.
- **LangChain/MCP SDK integration**: The Python MCP SDK (`mcp` package) and LangChain's `MultiServerMCPClient` do not natively support this pattern; you would implement the crypto layer as middleware in your gateway's HTTP handler [109].
- **AgentGateway (Rust-based successor)** currently uses stateful in-process session management and acknowledges this is problematic for distributed deployments. Their planned migration to stateless MCP validates the Envoy approach [110].

**9. Limitations and Open Questions.**
- **No standard**: Token-encoded sessions for MCP are Envoy-specific; no MCP spec requirement or recommendation exists for this pattern.
- **Replay window**: AES-GCM with random nonces prevents forgery but not replay. The upstream MCP server's own session validation provides replay protection.
- **Cold start cost**: If a gateway replica receives a request for a session it has never seen, it can decrypt the token but must re-establish upstream connections (the upstream session IDs are preserved, so resumption via `Last-Event-ID` is possible for SSE).
- **Capability staleness**: Capability flags encoded at session creation may become stale if upstream servers change capabilities mid-session.

**Q8 References:**

[103] Envoy AI Gateway Project. "The Reality and Performance of MCP Traffic Routing with Envoy AI Gateway." *Envoy AI Gateway Blog*. 2025. URL: https://aigateway.envoyproxy.io/blog/mcp-in-envoy-ai-gateway/. Accessed: 2026-03-27.

[104] Envoy AI Gateway Project. "Announcing Model Context Protocol Support in Envoy AI Gateway." *Envoy AI Gateway Blog*. 2025. URL: https://aigateway.envoyproxy.io/blog/mcp-implementation/. Accessed: 2026-03-27.

[105] Envoy AI Gateway Contributors. "ai-gateway: internal/mcpproxy/crypto.go, internal/mcpproxy/session.go." *GitHub (envoyproxy/ai-gateway)*. 2025-2026. URL: https://github.com/envoyproxy/ai-gateway/pull/1260. Accessed: 2026-03-27.

[106] Tetrate. "Envoy AI Gateway MCP Performance." *Tetrate Blog*. 2025. URL: https://tetrate.io/blog/envoy-ai-gateway-mcp-performance. Accessed: 2026-03-27.

[107] Envoy AI Gateway Project. "Helm Chart values.yaml (mcp.sessionEncryption)." *GitHub (envoyproxy/ai-gateway)*. 2025-2026. URL: https://github.com/envoyproxy/ai-gateway/blob/main/manifests/charts/ai-gateway-helm/values.yaml. Accessed: 2026-03-27.

[108] Envoy AI Gateway Project. "Model Context Protocol (MCP) Gateway Documentation." *Envoy AI Gateway Docs*. 2026. URL: https://aigateway.envoyproxy.io/docs/capabilities/mcp/. Accessed: 2026-03-27.

[109] LangChain. "Model Context Protocol (MCP) - Docs by LangChain." *LangChain Documentation*. 2026. URL: https://docs.langchain.com/oss/python/langchain/mcp. Accessed: 2026-03-27.

[110] spacewander. "Agentgateway Review: A Feature-Rich New AI Gateway." *DEV Community*. 2025. URL: https://dev.to/spacewander/agentgateway-review-a-feature-rich-new-ai-gateway-53lm. Accessed: 2026-03-27.

---

### Subtopic C: Policy Engine Integration

#### Q9: Cerbos and OPA for MCP Tool RBAC

**1. Cerbos + MCP: First-Class Integration.** Cerbos has built a first-class integration with Model Context Protocol servers, including an official demo repository and SDK support [111]. The architecture follows a three-tier pattern:

1. **Define policies** in declarative YAML specifying which roles/attributes can invoke which MCP tools
2. **Deploy Cerbos PDP** (Policy Decision Point) as a sidecar or central service
3. **Query Cerbos at session start** (and on permission changes) to enable/disable tools dynamically [112]

The key MCP SDK integration point is the `enable()`/`disable()` API on registered tools, combined with `sendToolListChanged()` to notify connected clients when the available tool set changes [113].

**Complete working server code** (Node.js, from the official Cerbos demo) [111]:

```javascript
import express from "express";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { GRPC } from "@cerbos/grpc";
import { randomUUID } from "node:crypto";

const cerbos = new GRPC("localhost:3593", { tls: false });

async function getServer({ user, sessionId }) {
  const server = new McpServer({ name: "CerbFinance MCP Server" });

  const tools = {
    list_expenses: server.tool("list_expenses", "Lists expenses.", {}, { title: "List Expenses" },
      async () => ({ content: [{ type: "text", text: "..." }] })),
    add_expense: server.tool("add_expense", "Adds an expense.", {}, { title: "Add Expense" },
      async () => ({ content: [{ type: "text", text: "..." }] })),
    approve_expense: server.tool("approve_expense", "Approves an expense.", {}, { title: "Approve Expense" },
      async () => ({ content: [{ type: "text", text: "..." }] })),
    delete_expense: server.tool("delete_expense", "Deletes an expense.", {}, { title: "Delete Expense" },
      async () => ({ content: [{ type: "text", text: "..." }] })),
  };

  const toolNames = Object.keys(tools);

  // Single batch authorization check against Cerbos PDP
  const authorizedTools = await cerbos.checkResource({
    principal: { id: user.id, roles: user.roles },
    resource: { kind: "mcp::expenses", id: sessionId },
    actions: toolNames,
  });

  // Deny-by-default: only enable explicitly allowed tools
  for (const toolName of toolNames) {
    if (authorizedTools.isAllowed(toolName)) {
      tools[toolName].enable();
    } else {
      tools[toolName].disable();
    }
  }

  server.sendToolListChanged(); // Notify client of filtered tool list
  return server;
}
```

The deny-by-default posture is inherent: tools start registered but disabled; only those explicitly allowed by Cerbos policy get enabled. The `sendToolListChanged()` call triggers the MCP `notifications/tools/list_changed` notification, causing compliant clients to re-fetch `tools/list` [113].

**2. Cerbos Policy Definition: RBAC + ABAC Conditions.**

*Basic RBAC policy* mapping MCP tool actions to roles (from the official demo) [111]:

```yaml
apiVersion: "api.cerbos.dev/v1"
resourcePolicy:
  version: "default"
  resource: "mcp::expenses"
  rules:
    - actions: ["list_expenses"]
      effect: EFFECT_ALLOW
      roles: ["admin", "manager", "user"]

    - actions: ["add_expense"]
      effect: EFFECT_ALLOW
      roles: ["user"]

    - actions: ["approve_expense", "reject_expense"]
      effect: EFFECT_ALLOW
      roles: ["admin", "manager"]

    - actions: ["delete_expense", "superpower_tool"]
      effect: EFFECT_ALLOW
      roles: ["admin"]
```

*ABAC conditions using CEL expressions* -- adding attribute-based constraints to role rules [112][114]:

```yaml
- actions: ["approve_expense"]
  effect: EFFECT_ALLOW
  roles: ["manager"]
  condition:
    match:
      expr: request.resource.attr.amount < 1000
```

*Rich ABAC condition patterns* from the Cerbos conditions documentation [114]:

```yaml
# Compound conditions (AND + OR + NOT)
condition:
  match:
    all:
      of:
        - expr: R.attr.status == "PENDING_APPROVAL"
        - any:
            of:
              - expr: R.attr.department == P.attr.department
              - expr: P.attr.geography == R.attr.geography
        - none:
            of:
              - expr: R.attr.flagged == true

# Time-based access control
condition:
  match:
    expr: >
      timestamp(R.attr.lastAccessed).timeSince() > duration("1h")

# IP-range restrictions
condition:
  match:
    expr: >
      P.attr.ipv4Address.inIPAddrRange("10.0.0.0/8")

# JWT claim checks (for agent identity tokens)
condition:
  match:
    expr: >
      "mcp-agent" in request.auxData.jwt.aud &&
      request.auxData.jwt.iss == "auth.internal"

# Set intersection (team membership)
condition:
  match:
    expr: >
      hasIntersection(R.attr.allowedTeams, P.attr.teams)
```

**3. Cerbos Python SDK for MCP Server Integration.** For Python-based MCP servers, the Cerbos gRPC SDK provides both sync and async clients [115]:

```python
from cerbos.sdk.grpc.client import AsyncCerbosClient
from cerbos.engine.v1 import engine_pb2
from google.protobuf.struct_pb2 import Value

# Async client for use in async MCP server handlers
async with AsyncCerbosClient("localhost:3593", tls_verify=False) as cerbos:
    principal = engine_pb2.Principal(
        id="agent-session-abc",
        roles={"manager"},
        attr={
            "department": Value(string_value="finance"),
            "geography": Value(string_value="US"),
        },
    )
    resource = engine_pb2.Resource(
        id="session-xyz",
        kind="mcp::expenses",
        attr={
            "amount": Value(number_value=500),
            "department": Value(string_value="finance"),
        },
    )
    allowed = await cerbos.is_allowed("approve_expense", principal, resource)
```

**4. Dynamic Re-evaluation on Permission Change.** Cerbos supports **live policy reloading** without server restarts. Policies stored on disk, in Git, or managed via Cerbos Hub are watched for changes and hot-reloaded into the PDP [112][116]. The recommended pattern for MCP is:

1. On each new MCP session/request, re-query Cerbos (the PDP always evaluates against current policies)
2. If a long-lived session detects policy changes (via webhook or polling), call `sendToolListChanged()` to force the client to re-fetch the tool list
3. Cerbos Hub provides centralized policy management with rollout controls for fleet-wide updates [116]

**5. OPA / Rego for MCP Tool Authorization.** OPA does not have a first-class MCP integration, but it serves as a general-purpose policy engine that can be wired into any authorization decision point. The integration pattern for MCP tool filtering requires building a custom middleware layer [117][118].

*Rego policy for per-agent MCP tool filtering with ABAC* (synthesized from OPA patterns) [119][120]:

```rego
package mcp.tools

import rego.v1

default allow := false

# Role-to-tool mapping (data layer, can be loaded from external source)
role_tools := {
    "admin":   {"list_expenses", "add_expense", "approve_expense", "delete_expense"},
    "manager": {"list_expenses", "approve_expense", "reject_expense"},
    "user":    {"list_expenses", "add_expense"},
}

# Base RBAC check
allow if {
    some role in input.principal.roles
    input.tool in role_tools[role]
}

# ABAC override: managers can only approve amounts < 1000
deny if {
    input.tool == "approve_expense"
    "manager" in input.principal.roles
    not "admin" in input.principal.roles
    input.resource.amount >= 1000
}

# Time-based restriction: no financial tools outside business hours
deny if {
    input.tool in {"approve_expense", "delete_expense", "add_expense"}
    hour := time.clock(time.now_ns())[0]
    hour < 8
}
deny if {
    input.tool in {"approve_expense", "delete_expense", "add_expense"}
    hour := time.clock(time.now_ns())[0]
    hour >= 18
}

# Final decision: allow only if base RBAC passes AND no deny rule fires
authorized if {
    allow
    not deny
}

# Bulk filter: return set of allowed tools for tools/list
allowed_tools contains tool if {
    some tool in input.requested_tools
    allow with input.tool as tool
    not deny with input.tool as tool
}
```

*Python integration pattern* (querying OPA via REST API for MCP) [118][121]:

```python
import httpx

OPA_URL = "http://localhost:8181/v1/data/mcp/tools/allowed_tools"

async def get_allowed_tools(principal: dict, requested_tools: list[str]) -> set[str]:
    """Query OPA for the set of tools this principal may use."""
    resp = await httpx.AsyncClient().post(OPA_URL, json={
        "input": {
            "principal": principal,
            "requested_tools": requested_tools,
            "resource": {},
        }
    })
    result = resp.json().get("result", [])
    return set(result)
```

For `tools/call` enforcement (per-invocation ABAC), a second query hits OPA with the full resource context:

```python
async def authorize_tool_call(principal: dict, tool: str, resource: dict) -> bool:
    resp = await httpx.AsyncClient().post(
        "http://localhost:8181/v1/data/mcp/tools/authorized",
        json={"input": {"principal": principal, "tool": tool, "resource": resource}}
    )
    return resp.json().get("result", False)
```

**6. Performance Comparison.**

*Cerbos PDP:*
- Sub-millisecond policy evaluations (often microsecond-range when deployed as sidecar) [116][122]
- After migrating from OPA's engine internally, Cerbos achieved up to **17x faster** decision evaluations [122]
- Stateless architecture: no DB synchronization overhead; in-memory evaluation
- A single instance handles thousands of requests/second

*OPA:*
- Benchmark data from official docs: median ~35 us (microseconds), 99th percentile ~134 us for RBAC policies [123]
- Simple policies: tens to hundreds of microseconds
- Memory: ~20x serialized data size (8 MB JSON data = ~160 MB RAM in OPA)
- Linear fragment of Rego engineered for near-constant-time evaluation [123]
- In-process evaluation (Go library or WASM) eliminates network overhead; REST API adds HTTP latency

Both engines comfortably achieve sub-millisecond decisions for typical MCP tool authorization policies. The bottleneck is network round-trip if the PDP runs as a separate service rather than sidecar/embedded.

**7. Key Architectural Differences for MCP Use Cases.**

| Dimension | Cerbos | OPA |
|---|---|---|
| **MCP Integration** | First-class SDK + demo repo | DIY via REST API or Go/WASM library |
| **Policy Language** | YAML + CEL (no code to learn) | Rego (Datalog-inspired, steeper curve) |
| **Built-in Concepts** | Principal, Resource, Action native | Schema-free; must define everything |
| **Deny-by-Default** | Inherent (no matching rule = deny) | Must set `default allow := false` |
| **Live Reload** | Built-in file/git/Hub watching | Requires bundle API or external sync |
| **Audit Trail** | Built-in structured decision logs | Requires decision log configuration |
| **Python SDK** | Official gRPC + async client | Community client (opa-python-client) or raw REST |
| **ABAC Conditions** | CEL expressions in YAML conditions block | Rego rules with arbitrary attribute checks |

**8. Recommendations for Per-Agent MCP RBAC.**

For building per-agent RBAC with ABAC conditions on MCP tools:

- **Choose Cerbos** if you want turnkey MCP integration, YAML-based policies non-engineers can review, built-in audit logging, and the fastest path to production. The `checkResource` batch API is purpose-built for the "filter N tools for principal P" pattern that `tools/list` requires [112].

- **Choose OPA** if you already have OPA deployed for Kubernetes/API gateway policies and want a single policy engine across the stack. OPA's Rego is more expressive for complex logic (graph traversal, aggregation) but requires more integration scaffolding for MCP [117][122].

- **Deny-by-default** is critical: in Cerbos, the absence of an EFFECT_ALLOW rule is an implicit deny. In OPA, you must explicitly set `default allow := false` and structure your policy with allow/deny rule separation [119].

- **Two-phase authorization** is recommended: Phase 1 at `tools/list` time (bulk filter by role/coarse attributes), Phase 2 at `tools/call` time (fine-grained ABAC with resource-specific attributes like amount, department, time) [112][124].

**Q9 References:**

[111] Cerbos. "cerbos-mcp-authorization-demo." *GitHub*. 2025. URL: https://github.com/cerbos/cerbos-mcp-authorization-demo. Accessed: 2026-03-27.

[112] Cerbos. "Dynamic Authorization for AI Agents: A Guide to Fine-Grained Permissions in MCP Servers." *Cerbos Blog*. 2025. URL: https://www.cerbos.dev/blog/dynamic-authorization-for-ai-agents-guide-to-fine-grained-permissions-mcp-servers. Accessed: 2026-03-27.

[113] Model Context Protocol. "Using notifications/tools/list_changed." *GitHub Discussions*. 2025. URL: https://github.com/orgs/modelcontextprotocol/discussions/76. Accessed: 2026-03-27.

[114] Cerbos. "Conditions." *Cerbos Documentation*. 2025. URL: https://docs.cerbos.dev/cerbos/latest/policies/conditions.html. Accessed: 2026-03-27.

[115] Cerbos. "cerbos-sdk-python." *GitHub*. 2025. URL: https://github.com/cerbos/cerbos-sdk-python. Accessed: 2026-03-27.

[116] Cerbos. "Enterprise-Grade Authorization for MCP Servers." *Cerbos*. 2025. URL: https://www.cerbos.dev/features-benefits-and-use-cases/dynamic-authorization-for-MCP-servers. Accessed: 2026-03-27.

[117] Open Policy Agent. "Open Policy Agent Documentation." *openpolicyagent.org*. 2025. URL: https://www.openpolicyagent.org/docs. Accessed: 2026-03-27.

[118] Open Policy Agent. "Integrating OPA." *openpolicyagent.org*. 2025. URL: https://www.openpolicyagent.org/docs/integration. Accessed: 2026-03-27.

[119] Gunasekara, C. "Implementing Policies with OPA -- Example Use Cases." *Medium*. 2024. URL: https://medium.com/@chathuragunasekera/implementing-policies-with-opa-example-use-cases-6f8f850cdec4. Accessed: 2026-03-27.

[120] Oso. "ABAC with Open Policy Agent (OPA)." *osohq.com*. 2024. URL: https://www.osohq.com/learn/abac-with-open-policy-agent-opa. Accessed: 2026-03-27.

[121] Turall. "OPA-python-client." *GitHub*. 2024. URL: https://github.com/Turall/OPA-python-client. Accessed: 2026-03-27.

[122] Cerbos. "Cerbos vs. OPA." *Cerbos Blog*. 2025. URL: https://www.cerbos.dev/blog/cerbos-vs-opa. Accessed: 2026-03-27.

[123] Open Policy Agent. "Policy Performance." *openpolicyagent.org*. 2025. URL: https://www.openpolicyagent.org/docs/policy-performance. Accessed: 2026-03-27.

[124] Cerbos. "MCP Permissions: Securing AI Agent Access to Tools." *Cerbos Blog*. 2025. URL: https://www.cerbos.dev/blog/mcp-permissions-securing-ai-agent-access-to-tools. Accessed: 2026-03-27.

---

### Summary

The deeper dive research across five questions reinforces and extends the General Understanding findings with concrete implementation details across three interrelated domains.

**Subtopic A (Python MCP Gateway Implementation)** established that FastMCP v3's proxy primitives -- `ProxyProvider`, `create_proxy()`, and `mount()` -- provide a clean foundation for multi-server aggregation with namespace isolation, credential injection via client factory closures, and middleware-based cross-cutting concerns [60-73]. IBM ContextForge then demonstrated what a production-grade deployment of these patterns looks like at scale: the "Fetch-Then-Release" DB pattern (releasing SQLAlchemy sessions before upstream network I/O) is a critical lesson for any async MCP gateway, and the session pooling architecture with circuit breakers and per-(URL, identity, transport) keying provides a proven blueprint for connection management [74-85]. Together, these two sources provide both the framework primitives and the production patterns needed for CommandClaw's Python gateway layer.

**Subtopic B (Phantom Token + Key Rotation Implementation)** provided the concrete cryptographic plumbing for the credential isolation architecture identified in the General Understanding. The phantom token pattern -- opaque tokens to agents, real credentials in the proxy, with HMAC-signed requests and dual-key overlap windows for zero-downtime rotation -- maps directly onto the MCP gateway's credential injection needs [86-102]. Envoy AI Gateway's token-encoded session architecture then offered an elegant alternative to distributed session stores: by encrypting upstream session routing state into the client-facing session ID with AES-256-GCM, any gateway replica can handle any request without shared state, achieving horizontal scalability with a single shared encryption seed [103-110]. The trade-off is the inability to revoke individual sessions without a blocklist, but the pattern's operational simplicity is compelling for the CommandClaw use case.

**Subtopic C (Policy Engine Integration)** grounded the authorization layer in concrete policy definitions and integration code. Cerbos's first-class MCP integration -- with `enable()`/`disable()` on tools, batch `checkResource` queries, and YAML+CEL policy definitions -- provides the fastest path to per-agent RBAC with ABAC conditions [111-124]. OPA offers more expressive Rego policies for complex logic but requires custom middleware scaffolding. The two-phase authorization pattern (coarse filtering at `tools/list`, fine-grained ABAC at `tools/call`) emerged as the recommended approach regardless of engine choice.

The three subtopics converge on a coherent architecture for CommandClaw: FastMCP proxy primitives for server aggregation, ContextForge patterns for production resilience, phantom tokens for credential isolation, token-encoded sessions for stateless scaling, and Cerbos/OPA for dynamic per-agent tool authorization -- all composable within a Python async gateway.
