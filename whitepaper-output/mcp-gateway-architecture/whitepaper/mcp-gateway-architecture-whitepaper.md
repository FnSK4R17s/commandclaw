# MCP Gateway Architecture: Secure Proxy Design for AI Agent Platforms

**Author:** Background Research Agent (BEARY)
**Date:** 2026-03-27
**Version:** 1.0

---

## Abstract

This whitepaper presents a comprehensive architecture for building a secure MCP (Model Context Protocol) gateway proxy for AI agent platforms. We analyze the MCP protocol's transport mechanics, survey the existing gateway landscape (Microsoft, Docker, Envoy, ContextForge, and others), and synthesize implementation-ready patterns across three critical domains: credential security via the phantom token pattern with rotating keys and HMAC-signed requests; stateless session management using Envoy's token-encoded approach; and role-based access control for tool visibility using externalized policy engines. We ground each pattern in concrete Python implementation details using FastMCP proxy primitives, FastAPI middleware, and production lessons from ContextForge's 150K-line codebase. The architecture targets CommandClaw-MCP, a Python-based MCP gateway for multi-agent orchestration, and recommends a layered security model where no single mechanism -- rotation, scoping, filtering, or proxy isolation -- is treated as sufficient on its own.

---

## 1. Introduction

An MCP gateway sits between AI agents and the tool servers they invoke, centralizing three concerns that are otherwise scattered across agent codebases: credential management, tool access control, and session routing [9]. Without a gateway, each agent process holds raw API keys, discovers all available tools regardless of authorization level, and maintains its own upstream connections -- a pattern that scales poorly and creates unbounded blast radius when credentials leak.

The core problem is structural. MCP is a stateful protocol: sessions carry negotiated capabilities and must maintain affinity across requests [1][4]. Agents operate at machine speed, executing thousands of tool calls before a human could intervene [41]. Credentials leaked from agent memory face a median five-minute window to first malicious use [27][28]. Traditional approaches -- static RBAC, periodic key rotation, sticky load balancing -- address these concerns individually but fail to compose into a coherent security posture.

This whitepaper synthesizes findings from the MCP specification (2025-11-25), six major gateway implementations, and current literature on credential isolation and agent authorization. The goal is a blueprint for CommandClaw-MCP: a Python async gateway that aggregates multiple MCP servers behind a single endpoint, manages credentials through the phantom token pattern, enforces per-agent tool visibility via externalized policy, and scales horizontally without shared state.

---

## 2. Background: MCP Protocol Mechanics

### 2.1 Wire Format: JSON-RPC 2.0

MCP uses JSON-RPC 2.0 over UTF-8 as its wire format [1][5]. Three message types define the protocol surface:

- **Requests** carry `jsonrpc`, `id`, `method`, and optional `params`. The `id` field is required for response correlation -- a proxy MUST preserve this identifier when forwarding [5].
- **Responses** carry `jsonrpc`, `id`, and either `result` or `error`, echoing the original request's `id` [5].
- **Notifications** carry `jsonrpc` and `method` but deliberately omit `id`. They generate no response -- a proxy must not block waiting for acknowledgment [5].

Batch operations (JSON arrays of requests) are supported; proxies must handle partial failures where some requests succeed and others error [5]. Standard error codes apply: `-32700` (parse error) through `-32099` (protocol-specific) [5].

The protocol is explicitly stateful -- connections maintain negotiated state from initialization through shutdown [1][4]. This statefulness is the root cause of the session management challenges explored in Section 6.

### 2.2 Transport Layers

The MCP spec (2025-11-25) defines two standard transports [1]:

**stdio** uses standard input/output of a child subprocess. Messages are newline-delimited (no Content-Length framing), the server MUST NOT write non-MCP data to stdout, and the client closes stdin to signal shutdown [1]. Performance is sub-millisecond latency at 10,000+ ops/sec, but the transport is limited to a single local client [3].

**Streamable HTTP** (current standard) consolidates the deprecated dual-endpoint SSE model into a single HTTP endpoint supporting both POST and GET [1]. Client-to-server messages are individual POSTs; the server responds with either `application/json` (simple request-response) or `text/event-stream` (SSE streaming for long-running operations) [1]. The client MUST include `Accept: application/json, text/event-stream` and support both response modes [1]. An optional GET endpoint opens an SSE stream for server-initiated messages [1].

The legacy HTTP+SSE transport (2024-11-05) required two separate endpoints -- an SSE endpoint for receiving and a POST endpoint for sending -- creating coordination complexity and HTTP/2 incompatibilities that motivated its deprecation [2][6].

### 2.3 Session Management

Sessions begin at initialization and are managed via the `Mcp-Session-Id` header [1]:

1. Server MAY assign a session ID in the `InitializeResult` response.
2. Session IDs MUST be globally unique, cryptographically secure (UUID, JWT, or hash), containing only visible ASCII (0x21-0x7E) [1].
3. Client MUST include `Mcp-Session-Id` on all subsequent requests; server SHOULD reject requests missing it with `400 Bad Request` [1].
4. Server MAY terminate sessions at any time (responding `404 Not Found`); client MUST start fresh on receiving 404 [1].
5. Client SHOULD send HTTP DELETE to explicitly terminate sessions [1].
6. Client MUST include `MCP-Protocol-Version` on all requests after initialization [1].

### 2.4 Resumability

Servers MAY attach `id` fields to SSE events per the SSE standard [1]. These function as per-stream cursors: on disconnection, the client resumes via GET with `Last-Event-ID`, and the server replays missed messages from the disconnected stream only [1][8]. Disconnection SHOULD NOT be interpreted as cancellation; clients SHOULD send explicit `CancelledNotification` [1].

### 2.5 Gateway-Relevant Protocol Constraints

For a proxy implementation, the following constraints are load-bearing:

- **Message ID preservation**: Every response must carry the exact `id` from its request [5].
- **Notification passthrough**: Messages without `id` require no response; the proxy must not block [5].
- **Bidirectional routing**: Servers can initiate requests to clients (e.g., `sampling/createMessage`), requiring full-duplex transport through the proxy [5].
- **Capability enforcement**: The proxy should validate messages against negotiated capabilities before forwarding [5].
- **Session affinity**: `Mcp-Session-Id` requires sticky sessions when load balancing (e.g., `ip_hash` in nginx) unless using token-encoded sessions [3].
- **SSE buffering**: Reverse proxies must disable response buffering for SSE streams, and heartbeats (~30s) prevent intermediate proxies from timing out [3].

---

## 3. Existing MCP Gateway Landscape

The gateway ecosystem has matured into three categories: managed platforms prioritizing developer velocity, security-first proxies for regulated industries, and infrastructure-native solutions offering maximum control [9].

### 3.1 Microsoft MCP Gateway (.NET, Kubernetes-Native)

Microsoft's gateway implements a dual-plane architecture [10]: a **data plane** handling runtime MCP request routing via `/adapters/{name}/mcp` endpoints and a dynamic Tool Gateway Router at `/mcp`, and a **control plane** providing RESTful management APIs for adapter lifecycle and tool registration [10]. Session management uses a distributed session store with session affinity, deployed as a Kubernetes StatefulSet behind a headless service [10][11]. Authentication integrates with Azure Entra ID, with RBAC roles (`mcp.admin`, `mcp.engineer`) controlling both planes [10].

### 3.2 Docker MCP Gateway (Go)

Docker's gateway runs MCP servers in isolated containers with restricted CPU (1 core), memory (2 GB), and no host filesystem access [12][13]. Written in Go, it aggregates servers from Docker catalog references, images, MCP Registry URLs, and local YAML files [13]. Credential management leverages Docker Desktop's native secrets store and built-in OAuth flows rather than environment variables [13]. The profile mechanism groups servers for consistent configuration across AI clients [13].

### 3.3 Envoy AI Gateway (Go + Envoy)

Envoy's MCP implementation leverages Envoy's existing networking stack for connection management, load balancing, and observability [14]. Its distinctive contribution is **token-encoded session management**: instead of a centralized store, the gateway encrypts upstream session routing state into the client-facing session ID itself, enabling any replica to handle any request without database lookups [14][15]. Two authentication layers operate independently: gateway-level OAuth for tool invocation authorization, and upstream authentication primitives for credential injection to external servers [14]. We analyze the token-encoded session pattern in depth in Section 6.

### 3.4 IBM ContextForge (Python, FastAPI)

ContextForge is the most relevant reference implementation for a Python gateway. It federates MCP servers, REST APIs, gRPC services, and A2A protocol implementations into a unified MCP-compliant interface [16]. Multi-transport exposure (HTTP/SSE, JSON-RPC, WebSocket, stdio, Streamable HTTP) allows clients to choose their preferred transport without backend changes [16]. The credential layer uses Fernet encryption (AES-128-CBC + HMAC-SHA256) with Argon2id key derivation at rest, supports JWT/OAuth/OIDC, and isolates tokens per user session [16][84]. Its production architecture -- async SQLAlchemy, orjson serialization, Redis-backed session affinity, circuit breakers, and OpenTelemetry -- provides a battle-tested blueprint [16][77]. We extract detailed implementation lessons in Section 8.

### 3.5 Other Notable Implementations

**Agentic Community Gateway** (Python/FastAPI) implements Virtual MCP Servers with tool aliasing, session multiplexing, vector-based semantic tool discovery, and centralized vault integration with Fernet-encrypted storage [17]. **LiteLLM** provides a YAML-configured MCP Gateway with per-API-key access control and OpenAI-compatible tool transformation [18]. **MCProxy** (Rust) features a two-tier middleware architecture with regex-based tool filtering and security rules [23]. **Permit MCP Gateway** auto-generates OPA/Rego policies by inspecting upstream tools and uses a Zanzibar-inspired relationship graph for RBAC+ABAC+ReBAC [43].

### 3.6 Lightweight Python Proxies

**mcp-proxy** (PyPI) is a transport bridge operating in stdio-to-HTTP and HTTP-to-stdio modes, supporting multiple named servers behind a single proxy instance [19]. **FastMCP** provides native proxy primitives (`ProxyProvider`, `create_proxy()`, `mount()`) for multi-server aggregation with namespace isolation, but lacks built-in credential management [20][21]. **AWS MCP Proxy** handles SigV4 authentication for Bedrock-hosted MCP servers [22].

### 3.7 Cross-Cutting Patterns

Three patterns recur across implementations:

1. **Credential centralization**: Every gateway centralizes credential storage and injects appropriate credentials per-request, eliminating credential sprawl [9][25].
2. **Multi-server aggregation**: Namespace prefixing (FastMCP), tool aliasing (Agentic Community), dynamic routing (Microsoft, Envoy), and policy-based filtering (Envoy, MCProxy) all solve the same problem of presenting a unified tool surface [10][14][20][23].
3. **Session management bifurcation**: Distributed session stores (Microsoft, ContextForge) versus token-encoded sessions (Envoy) represent the two scaling strategies, with no hybrid approaches observed [15][16].

---

## 4. Credential Security: The Phantom Token Pattern

### 4.1 Why Key Rotation Alone Fails

GitGuardian research establishes that the median time from credential leak to first malicious use is five minutes [27][28]. Even hourly rotation provides 60 minutes of exposure -- 12x longer than the attacker's exploitation window. A 90-day rotation cycle provides 129,600 minutes [27]. Rotation is a lagging control that addresses credentials after exploitation, not before [27].

Static API keys compound the problem along four blast-radius dimensions: temporal validity remaining, scope of permitted operations, number of systems accepting the credential, and detectability of misuse [27][28]. Copies of a leaked static key exist in .env files, CI/CD logs, integrations, and documentation, making complete revocation impossible [27].

### 4.2 Phantom Token Architecture

The phantom token pattern (originated by Curity, now generalized for AI agents) splits authentication into two layers: an **opaque reference token** visible to agents, and a **real credential** known only to the gateway [86][87]. The agent never sees the real credential. On each request, the gateway validates the opaque token, retrieves the real credential from a secure store, injects it, and forwards to the upstream API [88][89].

For MCP gateways, the mapping is direct: the MCP client receives a meaningless session token; the gateway intercepts tool calls, validates the phantom token, and injects scoped real credentials before forwarding [89][90].

A leaked phantom token provides only: temporal access (short TTL), operational access through the proxy only, scope-restricted operations, and identity-bound sessions. A leaked real credential works anywhere the upstream API accepts it, from any IP, for any operation [38]. The proxy model also enables genuinely instant revocation: delete the token from the store, and every subsequent request fails [27].

### 4.3 Token Generation

**Opaque session tokens** (what agents receive) use `secrets.token_urlsafe(32)` to produce 256-bit cryptographically random strings -- pure random references with no embedded meaning, serving as lookup keys into a server-side credential map [91][88]:

```python
import secrets
phantom_token = secrets.token_urlsafe(32)  # 256-bit, URL-safe base64
```

**HMAC-signed request tokens** provide per-request integrity verification. The session token doubles as the HMAC key, meaning only the agent holding the correct phantom token can produce valid signatures [92][93]. The canonical string includes method, path, timestamp, nonce, and body hash:

```python
import hmac, hashlib, base64

def sign_request(session_token: str, method: str, path: str,
                 timestamp: str, nonce: str, body: bytes) -> str:
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = '\n'.join([method.upper(), path, timestamp, nonce, body_hash])
    signature = hmac.new(
        session_token.encode('utf-8'),
        canonical.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(signature).decode('utf-8')
```

Verification MUST use `hmac.compare_digest()` for constant-time comparison to prevent timing attacks [92][93]. Replay prevention requires timestamped headers within the signed payload, rejecting requests older than 5 minutes, plus nonce tracking [93][92].

### 4.4 Dual-Key Overlap Window for Zero-Downtime Rotation

The overlap window is the mechanism that enables zero-downtime rotation. During any dual-key period, both old and new keys validate requests [26][95][96]:

```
T=0:00  Token A active (current generation)
T=0:55  Rotation triggered: generate Token B
T=0:55  Token B becomes "current"; Token A moves to "previous"
T=0:55  Both A and B valid (overlap window begins)
T=1:00  Token A expires (overlap window ends after 5 minutes)
T=1:00  Only Token B valid
```

For hourly rotation, a 5-minute overlap window balances clock-skew tolerance against exposure duration [30]. The implementation maintains current and previous token generations:

```python
class RotatingTokenManager:
    def __init__(self, rotation_interval: int = 3600, overlap_window: int = 300):
        self.rotation_interval = rotation_interval
        self.overlap_window = overlap_window
        self._lock = threading.Lock()
        self._current_token: str = ""
        self._previous_token: Optional[str] = None
        self._previous_expires: float = 0

    def validate(self, token: str) -> bool:
        with self._lock:
            if hmac.compare_digest(token, self._current_token):
                return True
            if (self._previous_token and
                time.time() < self._previous_expires and
                hmac.compare_digest(token, self._previous_token)):
                return True
            return False
```

The Azure Key Vault dual-credential rotation tutorial formalizes this as an alternating primary/secondary key strategy [95].

### 4.5 Token-to-Credential Lookup

The proxy maintains a mapping from phantom tokens to real credentials. The credential store supports multiple injection modes -- header injection (`Authorization: Bearer {real_key}`), query parameter injection, Basic Auth, and custom path-based injection [88]. Credential backends include system keyring, HashiCorp Vault, AWS Secrets Manager, and environment variables [94].

```python
@dataclass
class CredentialEntry:
    real_credential: str
    upstream_url: str
    header_name: str = "Authorization"
    credential_format: str = "Bearer {}"
    expires_at: Optional[float] = None

@dataclass
class PhantomSession:
    phantom_token: str
    hmac_key: str
    credentials: Dict[str, CredentialEntry] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0

class TokenStore:
    def __init__(self):
        self._sessions: Dict[str, PhantomSession] = {}
        self._prev_sessions: Dict[str, PhantomSession] = {}  # overlap window

    def get(self, phantom_token: str) -> Optional[PhantomSession]:
        session = self._sessions.get(phantom_token)
        if session and not self._is_session_expired(session):
            return session
        session = self._prev_sessions.get(phantom_token)
        if session and not self._is_session_expired(session):
            return session
        return None
```

### 4.6 Distributing Rotated Tokens to Agents

Three distribution patterns serve different deployment models:

1. **Environment variable injection at session start**: The proxy spawns the agent with `OPENAI_API_KEY=<phantom_token>` and `OPENAI_BASE_URL=http://127.0.0.1:<port>/openai`. Standard LLM SDKs respect base URL overrides and route through the proxy automatically [88][89].

2. **Session creation endpoint**: The orchestrator calls `POST /proxy/sessions` to receive a phantom token, then passes it to the agent. Sessions auto-expire (default 1 hour, max 24 hours) [88].

3. **Push notification on rotation**: For long-running agents, the proxy notifies via SSE or webhook that a new token is available. The overlap window ensures agents using the old token during the polling interval are not rejected [96].

### 4.7 Full Proxy Pipeline

The complete request lifecycle in a phantom-token MCP gateway [88][94]:

1. Agent sends request with phantom token in `Authorization` header
2. Proxy extracts phantom token and HMAC signature headers
3. Timestamp freshness check (reject if >5 min drift)
4. Nonce uniqueness check (reject replays)
5. Token lookup in current generation, then previous generation (overlap window)
6. HMAC signature verification using phantom token as key (constant-time)
7. Service prefix extraction from URL path determines credential entry
8. Real credential fetched from backend; refreshed if TTL expired
9. Phantom token and HMAC headers stripped from request
10. Real credential injected in configured format
11. Request forwarded to upstream over TLS
12. Response streamed back to agent without buffering (supports SSE/chunked)
13. Audit log entry written (no sensitive data -- headers, bodies, query params excluded)

### 4.8 Security Hardening

- **Memory protection**: Real credentials should be zeroed on deallocation. Python lacks Rust's `Zeroizing<String>`, but `ctypes.memset` on bytearrays or `mmap`-backed buffers provide explicit wipe capability [88].
- **DNS rebinding protection**: Resolve hostnames once, check all resolved IPs against a deny CIDR list, connect using pre-resolved addresses [88][101].
- **Bind to loopback only**: The proxy binds to `127.0.0.1:0` (ephemeral port), requiring both the random port AND the phantom token for access [94].
- **MCP spec mandates**: Tokens must be audience-bound, token passthrough is forbidden, and MCP servers must not accept tokens not explicitly issued for them [101].

---

## 5. Rotation Interval Analysis and Trade-Offs

### 5.1 Industry Benchmarks

| Environment | Rotation Interval | Rationale |
|---|---|---|
| High-security (PCI DSS) | 30-90 days | Compliance-driven [26] |
| Standard production APIs | 90-180 days | Operational cost vs. exposure [26] |
| AWS STS temporary credentials | 15 min - 12 hours | Cloud-native ephemeral [36] |
| SPIFFE SVIDs | Minutes to 1 hour | Zero-trust native [34][35] |
| Dynamic secrets (Vault) | Minutes to hours | Workload-lifecycle-bound [31] |

### 5.2 Dynamic vs. Rotated Secrets

Rotated secrets offer lower latency (pre-created), simpler application logic, and can be shared across instances, but have longer exposure windows. Dynamic secrets are unique per workload with shorter TTLs and isolated revocation impact, but create a runtime dependency on the secrets manager [31].

For a credential proxy, the hybrid approach is recommended: rotated secrets for the proxy-to-vault relationship (high availability requirement) and dynamic/phantom tokens for consumer-to-proxy relationships (high security requirement) [31].

### 5.3 Overlap Window Security Surface

During any dual-key overlap period, both old and new keys are valid. Longer overlap provides more consumer flexibility but increases the attack surface if the old key was compromised before rotation was triggered [26]. For hourly rotation, a 5-minute overlap window balances clock-skew tolerance against exposure duration [30].

### 5.4 Secrets Manager Unavailability

A runtime dependency on the secrets manager creates an availability risk: if Vault becomes unavailable when rotation is due, applications cannot refresh credentials [31]. The recommended mitigation: cache the current valid credential with a bounded grace period, extending the current key's validity by one additional interval rather than failing open [31]. Alert on rotation failures with exponential backoff retry (up to 3 attempts) [30].

### 5.5 Emerging Standards

CAEP (Continuous Access Evaluation Profile) enables longer token lifespans through real-time risk assessment and immediate revocation upon security events [29]. WIMSE (Workload Identity in Multi-System Environments) standardizes short-lived token management for cloud-native architectures [29]. The industry is moving toward context-aware credential lifecycle management rather than fixed-interval rotation.

---

## 6. Stateless Session Management: Token-Encoded Sessions

### 6.1 The Problem

MCP is stateful: a session ID must be reused across calls so servers maintain context [103]. When a gateway fans a single client session out to N upstream sessions, it must route subsequent requests back to the correct upstream session [104]. The conventional solutions -- sticky sessions and distributed session stores -- introduce operational complexity or single points of failure [108].

### 6.2 Envoy's Token-Encoding Architecture

Envoy AI Gateway solves this by encoding all upstream session routing state directly into the client-facing session ID [103][104]:

1. **Session initialization**: Client connects; gateway establishes upstream sessions with each backend.
2. **Composite session ID construction**: The gateway serializes a composite string containing route name, authenticated subject, and per-backend entries (backend name, base64-encoded upstream session ID, capability flags):
   ```
   {routeName}@{subject}@{backend1}:{base64(sessionID1)}:{capHex1},{backend2}:{base64(sessionID2)}:{capHex2}
   ```
3. **Encryption**: The composite string is encrypted using PBKDF2 + AES-256-GCM and returned as the `Mcp-Session-Id` header [105].
4. **Routing**: Any replica decrypts the session ID, parses the composite, and routes to the correct upstream -- no database lookup required [103].

### 6.3 Cryptographic Implementation

The implementation uses PBKDF2 with SHA-256 (16-byte random salt, 32-byte derived key, configurable iteration count) and AES-256-GCM (random 12-byte nonce per encryption) [105]. The wire format is `base64(salt || nonce || ciphertext)` [105].

Key rotation uses `FallbackEnabledSessionCrypto`: a secondary seed+iterations pair is tried if primary decryption fails, enabling zero-downtime seed rotation [105][107]. All replicas share the same seed -- the sole shared secret [103][107].

Each `compositeSessionEntry` contains backend name, upstream session ID, last SSE event ID (for reconnection), and a 9-bit capability bitmask encoded as 3-char hex covering Tools, ToolsListChanged, Prompts, PromptsListChanged, Logging, Resources, ResourcesListChanged, ResourcesSubscribe, and Completions [105]. The subject field is bound into the encrypted token to prevent session hijacking [105].

### 6.4 Performance

| Configuration | Session-creation overhead |
|---|---|
| Default (100k PBKDF2 iterations) | ~tens of ms [103] |
| Tuned (~100 iterations) | ~1-2 ms [106] |

The PBKDF2 cost is paid only on session creation (and re-establishment after reconnection), not on every JSON-RPC message within an existing session [105]. MCP tool calls occur within LLM conversation turns that themselves take seconds, making sub-millisecond gateway overhead irrelevant in practice [106].

### 6.5 Trade-Offs vs. Distributed Session Stores

| Dimension | Token-Encoded (Envoy) | Redis/DB Store | Sticky Sessions |
|---|---|---|---|
| Horizontal scaling | Any replica, no state sync [103] | HA Redis required | Tied to instance |
| Operational complexity | Single shared secret | Redis deployment + monitoring | LB affinity config |
| Per-request latency | ~1-2ms tuned [106] | ~0.5-2ms network RTT [108] | Zero |
| Failure mode | No SPOF; secret loss = rotate [103] | Redis down = sessions lost | Instance failure = lost |
| Token size | Grows with backend count | Fixed UUID | Fixed UUID |
| Session invalidation | Cannot revoke without blocklist | Immediate DELETE | Instance-local |
| Key rotation | Fallback seed [107] | N/A | N/A |

The critical limitation is identical to the JWT revocation problem: individual sessions cannot be revoked without maintaining a server-side blocklist. A lightweight Redis set of revoked session hashes can complement the approach without requiring full session state in Redis [15].

### 6.6 Python Portability

The pattern is directly portable. `cryptography.hazmat.primitives.kdf.pbkdf2.PBKDF2HMAC` handles KDF and `cryptography.hazmat.primitives.ciphers.aead.AESGCM` handles AES-256-GCM. Python's `hashlib.pbkdf2_hmac` is C-accelerated and performs comparably to Go [15]. In an async gateway, encryption/decryption should be offloaded to a thread pool via `asyncio.to_thread()` to avoid blocking the event loop [109]. HTTP header size limits (typically 8-16 KB) set an upper bound on backend count per session.

### 6.7 Limitations

- **No standard**: Token-encoded sessions are Envoy-specific; no MCP spec requirement exists [15].
- **Replay window**: AES-GCM prevents forgery but not replay; upstream MCP server session validation provides replay protection [105].
- **Cold start**: A replica receiving a request for an unseen session can decrypt the token but must re-establish upstream connections (resumption via `Last-Event-ID` is possible for SSE) [105].
- **Capability staleness**: Flags encoded at session creation may become stale if upstream servers change capabilities mid-session [105].

---

## 7. Tool Access Control: RBAC for Agents

### 7.1 Why Traditional RBAC Fails

Traditional RBAC assigns static roles with fixed permission sets -- fundamentally mismatched to AI agent behavior [41]. Three deficiencies emerge:

**Over-permissioning**: Agents lack contextual judgment. An agent with excessive permissions will "relentlessly try to achieve" goals using all available access, making prompt injection attacks significantly more dangerous [41].

**Role explosion**: Creating narrow roles like `file-reader-agent-role-for-project-x` leads to unmanageable proliferation. Agents need "hyper-specific, short-lived access patterns that static roles cannot express" [41].

**Machine-speed risk amplification**: Agents execute orders of magnitude faster than humans. What causes "limited damage before someone notices" with a human becomes catastrophic within seconds [41].

The emerging consensus calls for hybrid RBAC+ABAC models with context-aware, task-scoped permissions enforced via centralized policy decision points [42][44].

### 7.2 MCP Authorization Foundation

The MCP spec defines authorization using OAuth 2.1 [46]. MCP servers are OAuth resource servers; clients are OAuth clients. Scopes map to tool permissions via `WWW-Authenticate` headers. Step-up authorization handles progressive permission escalation: when a client has a token but needs additional permissions, the server returns `403 Forbidden` with `error="insufficient_scope"` [46].

The November 2025 spec update added: default scope names (SEP-835) for ecosystem-wide predictability [47], M2M OAuth via client credentials (SEP-1046) for headless agents [47], and enterprise IdP controls (SEP-990/XAA) routing auth through corporate identity providers [48].

Critically, the spec itself does NOT mandate per-client tool filtering. The `tools/list` response returns all tools the server exposes; filtering is left to servers and gateways [49]. The `notifications/tools/list_changed` notification enables dynamic filtering by signaling clients to re-fetch the tool list [49].

### 7.3 Dual-Layer Enforcement

The CodiLime pattern establishes that neither discovery-time filtering nor call-time enforcement is sufficient alone [50]:

**Discovery filtering** (`ScopeFilterMiddleware`) inspects caller JWT scopes before returning the tool list, "constraining the LLM's reasoning space before any action attempts" [50]. This reduces context window consumption and prevents unauthorized tool discovery.

**Call-time enforcement** (decorator-based) retrieves the JWT from request context, checks scope membership, and denies with audit logging if the scope is absent [50]:

```python
@mcp.tool()
@require_scope("mcp:ctrl-plane:write")
def set_interface_state(device: str, interface: str, state: str) -> str:
    ...
```

"Discovery filtering without call-time enforcement can be bypassed by an attacker who skips the agent and sends raw HTTP requests" [50]. Both layers are required.

### 7.4 Externalized Policy: Cerbos

Cerbos provides a first-class MCP integration with an official demo repository [111]. The architecture follows three steps: define YAML policies mapping roles to tool actions, deploy a Cerbos PDP as a sidecar or central service, and query Cerbos at session start to enable/disable tools dynamically [112].

**RBAC policy**:
```yaml
resourcePolicy:
  resource: "mcp::expenses"
  rules:
    - actions: ["list_expenses"]
      effect: EFFECT_ALLOW
      roles: ["admin", "manager", "user"]
    - actions: ["approve_expense"]
      effect: EFFECT_ALLOW
      roles: ["admin", "manager"]
    - actions: ["delete_expense"]
      effect: EFFECT_ALLOW
      roles: ["admin"]
```

**ABAC conditions** extend role checks with CEL expressions [112][114]:
```yaml
- actions: ["approve_expense"]
  effect: EFFECT_ALLOW
  roles: ["manager"]
  condition:
    match:
      expr: request.resource.attr.amount < 1000
```

Rich conditions support compound logic (AND/OR/NOT), time-based access control, IP-range restrictions, JWT claim checks, and set intersections for team membership [114].

The Python SDK provides async gRPC integration:
```python
from cerbos.sdk.grpc.client import AsyncCerbosClient

async with AsyncCerbosClient("localhost:3593", tls_verify=False) as cerbos:
    principal = engine_pb2.Principal(id="agent-session-abc", roles={"manager"})
    resource = engine_pb2.Resource(id="session-xyz", kind="mcp::expenses",
        attr={"amount": Value(number_value=500)})
    allowed = await cerbos.is_allowed("approve_expense", principal, resource)
```

Deny-by-default is inherent: tools start registered but disabled; only those explicitly allowed by policy get enabled [51]. Cerbos supports live policy reloading without server restarts, and the batch `checkResource` API is purpose-built for the "filter N tools for principal P" pattern [112][116].

### 7.5 Externalized Policy: OPA

OPA serves as a general-purpose policy engine using Rego, applicable when the organization already deploys OPA for Kubernetes or API gateway policies [117][118]. A Rego policy for MCP tool filtering with ABAC:

```rego
package mcp.tools

default allow := false

role_tools := {
    "admin":   {"list_expenses", "add_expense", "approve_expense", "delete_expense"},
    "manager": {"list_expenses", "approve_expense"},
    "user":    {"list_expenses", "add_expense"},
}

allow if {
    some role in input.principal.roles
    input.tool in role_tools[role]
}

deny if {
    input.tool == "approve_expense"
    "manager" in input.principal.roles
    not "admin" in input.principal.roles
    input.resource.amount >= 1000
}

authorized if { allow; not deny }

allowed_tools contains tool if {
    some tool in input.requested_tools
    allow with input.tool as tool
    not deny with input.tool as tool
}
```

Integration uses OPA's REST API:
```python
async def get_allowed_tools(principal: dict, requested_tools: list[str]) -> set[str]:
    resp = await httpx.AsyncClient().post(
        "http://localhost:8181/v1/data/mcp/tools/allowed_tools",
        json={"input": {"principal": principal, "requested_tools": requested_tools}}
    )
    return set(resp.json().get("result", []))
```

### 7.6 Cerbos vs. OPA Decision Matrix

| Dimension | Cerbos | OPA |
|---|---|---|
| MCP Integration | First-class SDK + demo [111] | DIY via REST or WASM [117] |
| Policy Language | YAML + CEL | Rego (steeper curve) |
| Performance | Sub-ms; 17x faster than OPA internals [122] | Median ~35us, p99 ~134us [123] |
| Deny-by-Default | Inherent | Explicit `default allow := false` |
| Live Reload | Built-in file/git/Hub watching [116] | Bundle API or external sync |
| Python SDK | Official gRPC + async [115] | Community client or raw REST [121] |

Both engines comfortably achieve sub-millisecond decisions. The bottleneck is network round-trip if the PDP runs as a separate service rather than sidecar.

### 7.7 Two-Phase Authorization

The recommended pattern is two-phase [112][124]:

**Phase 1 (tools/list)**: Bulk filter by role and coarse attributes. The gateway queries the policy engine with the principal's identity and receives a set of allowed tool names. Only these tools appear in the `tools/list` response. This constrains the LLM's reasoning space before any action attempts.

**Phase 2 (tools/call)**: Fine-grained ABAC with resource-specific attributes (amount, department, time-of-day). The gateway queries the policy engine with the full invocation context before forwarding the call. This catches cases where discovery-time permissions were correct but runtime conditions have changed.

### 7.8 Alternative: Capability-Based Delegation

The MCP Delegation Gateway proposes a cryptographic capability model where "delegated permissions can only shrink -- never expand" [55]. Signed, tamper-evident receipts back every authorization decision, with a 7-step verification pipeline ensuring monotonic capability reduction [55]. This model suits agent-to-agent delegation chains where RBAC role assignments become meaningless.

---

## 8. Python Implementation Architecture

### 8.1 FastMCP Proxy Primitives

FastMCP v3 organizes around Components (Tools, Resources, Prompts), Providers (sources of components), and Transforms (middleware). The proxy system is built on these primitives -- "a Provider plus a Transform" [60].

**ProxyProvider** extends `Provider` and proxies component discovery and execution via a client factory callable [62]. The factory pattern (`Callable[[], Client] | Callable[[], Awaitable[Client]]`) ensures session isolation: each proxy component independently manages its own client session [62]. Caching uses per-component-type entries with TTL-based freshness (default 300s) [62].

**Multi-server aggregation** mounts multiple `create_proxy()` instances with distinct namespaces:

```python
from fastmcp import FastMCP, create_proxy

gateway = FastMCP(name="Gateway")
gateway.mount(create_proxy("http://weather-api.internal/mcp"), namespace="weather")
gateway.mount(create_proxy("http://db-api.internal/mcp"), namespace="db")
gateway.mount(create_proxy("./local_tools.py"), namespace="local")
```

This produces tools like `weather_get_forecast`, `db_query`, `local_search`. Each proxy component routes calls back to its original upstream using the `_backend_name` mechanism -- namespace prefixing works without breaking upstream routing because the proxy calls the upstream with the original name while the gateway exposes the prefixed name [62][65].

**Credential injection** follows three patterns:

*Pattern A*: Per-upstream bearer tokens via client factory customization [66]:
```python
def make_authed_proxy(url: str, token: str):
    def factory():
        return Client(url, auth=BearerAuth(token=token))
    return FastMCPProxy(client_factory=factory, name=f"proxy-{url}")
```

*Pattern B*: Inbound credential extraction via middleware, forwarded to upstream via context state [67][68]:
```python
class CredentialInjectionMiddleware(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        headers = get_http_headers() or {}
        metadata = json.loads(headers.get("x-metadata", "{}"))
        if not validate_token(metadata.get("token")):
            raise ToolError("Unauthorized")
        context.fastmcp_context.set_state("user_creds", metadata)
        return await call_next(context)
```

*Pattern C*: Dynamic per-user credential injection via client factory closures capturing per-request context [62][69].

**Middleware system** provides hooks at multiple granularities: `on_message` (all traffic), `on_call_tool` / `on_read_resource` / `on_get_prompt` (operation-specific), and `on_list_tools` / `on_list_resources` (filtering) [67]. Key patterns include tag-based authorization, tool visibility filtering, input sanitization, and response enrichment [67].

### 8.2 ContextForge Production Lessons

ContextForge's 150K-line codebase reveals several patterns critical for production Python gateways:

**The Fetch-Then-Release DB pattern**: Under 1,000 concurrent users, 65% of DB connections were stuck idle-in-transaction while waiting for upstream MCP server HTTP responses [76]. The root cause: `invoke_tool()` held a SQLAlchemy session across the entire request lifecycle, including network calls (100ms-4+ minutes). The fix:

1. Eager-load with `joinedload()` -- single query for tool + relationships
2. Copy to local variables -- extract all needed fields
3. `expunge()` + `close()` -- release the connection before network I/O
4. Network operations with no DB session held
5. Fresh session for write-back via `@asynccontextmanager`

This dropped connection hold time from 100ms-4min to <50ms, increasing max concurrent requests from ~200 to ~3,000+ [76]. Any MCP gateway that proxies tool calls must decouple DB sessions from upstream network I/O.

**MCP session pooling**: Connection reuse to upstream servers delivers 10-20x latency reduction [77][80]. The pool key is `(URL, identity_hash, transport_type)`, ensuring different users never share sessions [78]. An integrated circuit breaker opens after 5 failures for 60 seconds before entering half-open state [77][78].

**Transport bridging**: The `mcpgateway.translate` module wraps any stdio-only MCP server and exposes it over SSE [79]. This solves the common problem of connecting HTTP-based gateways to stdio-only servers without modification.

**Credential encryption at rest**: Fernet (AES-128-CBC + HMAC-SHA256) with Argon2id key derivation, per-secret unique salt embedded in a self-describing JSON bundle `{"kdf":"argon2id","t":3,"m":65536,"p":1,"salt":"<base64>","token":"gAAAAA..."}` [84][77]. This supports algorithm migration without breaking existing ciphertext.

**Dual observability**: Internal self-contained tracing (Gantt charts, flame graphs, zero overhead when disabled) plus external OTLP export to Jaeger/Zipkin/Tempo [80][82]. Pragmatic for development through production.

### 8.3 Performance Characteristics

- HTTP proxy adds 200-500ms latency per hop [63]
- Namespace depth compounds latency (nested mounts multiply round-trips) [63]
- Cache TTL (default 300s) means upstream changes may take 5 minutes to propagate [62]
- Tool overload: bundling too many servers can overwhelm LLM context with tool descriptions [64]
- Session pooling (ContextForge pattern) reduces per-call latency by 10-20x after initial connection [80]

---

## 9. Recommendations for CommandClaw-MCP

Based on the analysis, we recommend the following architecture for CommandClaw-MCP:

### 9.1 Transport Layer

Use **Streamable HTTP** as the primary client-facing transport, with **stdio bridging** for local MCP servers. FastMCP's `create_proxy()` handles both transport types natively [20]. Support backward compatibility with legacy SSE by attempting Streamable HTTP first and falling back to SSE on 4xx responses [1].

### 9.2 Multi-Server Aggregation

Use FastMCP's `mount()` with namespace prefixing as the default aggregation strategy. For advanced use cases (tool aliasing, semantic discovery), build a custom `AggregateProvider` that extends FastMCP's built-in one [61][65]. Limit exposed tools per-session to prevent LLM context overload -- the Virtual MCP pattern of on-demand discovery (up to 8 tools per request) reduces token usage by 60-85% [54].

### 9.3 Credential Management

Implement the **phantom token pattern** as the primary credential isolation mechanism:

- Agents receive opaque tokens via `secrets.token_urlsafe(32)` [91]
- Real credentials stored in an encrypted vault (Fernet + Argon2id, following ContextForge's self-describing JSON format) [84]
- HMAC-signed requests using the phantom token as key, with 5-minute timestamp tolerance and nonce tracking [92][93]
- Hourly rotation with 5-minute dual-key overlap windows [30][96]
- Credential distribution via environment variable injection for short-lived agents, session creation endpoint for long-lived agents [88]

For secrets manager unavailability: cache the current credential with a one-interval grace period rather than failing open [31].

### 9.4 Session Management

Start with a **Redis-backed session store** (simpler, immediate revocation) and plan migration to **token-encoded sessions** (Envoy pattern) when horizontal scaling demands it. The Python `cryptography` library provides all required primitives [15][105]. Use `asyncio.to_thread()` for PBKDF2+AES-GCM operations to avoid blocking the event loop.

For the Redis phase, apply ContextForge's session pooling pattern: key by `(URL, identity_hash, transport_type)`, integrate circuit breakers, and use health checks before reuse [78].

### 9.5 Tool Access Control

Implement **dual-layer enforcement** with an externalized policy engine [50]:

- Phase 1 (discovery): `on_list_tools` middleware queries the policy engine with the principal's identity, returning only allowed tools [67]
- Phase 2 (invocation): `on_call_tool` middleware queries with full resource context before forwarding [67]
- Deny-by-default posture: new sessions start with no tools enabled [51]
- Use `notifications/tools/list_changed` to dynamically update tool lists when permissions change [49][113]

**Choose Cerbos** for the policy engine: it provides first-class MCP integration, YAML+CEL policies, batch `checkResource` for efficient tool filtering, and an official Python async gRPC SDK [111][115]. Fall back to OPA if the deployment already standardizes on Rego [117].

### 9.6 Database and Async Patterns

Use SQLAlchemy 2.0 async ORM with the **Fetch-Then-Release** pattern: eager-load, copy to locals, `expunge()` and release the session before any upstream network I/O [76]. Size the connection pool conservatively (default 200, overflow 10) with pre-ping health checks [77].

### 9.7 Observability

Integrate OpenTelemetry from the start: OTLP traces, Prometheus metrics for circuit breaker state and rotation health, and structured JSON logging [82]. Track: rotation success/failure counts, active key inventory, key age distribution, validation failure rates, and per-tool authorization decisions [30][50].

---

## 10. Conclusion

Building a secure MCP gateway requires layered defenses across four domains: transport fidelity, credential isolation, session management, and tool access control. No single mechanism is sufficient alone.

The phantom token pattern eliminates the fundamental problem of credential sprawl by ensuring agents never hold real credentials, while HMAC-signed requests and dual-key rotation provide defense-in-depth against token theft. Token-encoded sessions enable stateless horizontal scaling, though they trade individual session revocation for operational simplicity. Dual-layer tool authorization (discovery filtering + call-time enforcement) backed by an externalized policy engine ensures agents operate within precisely scoped permissions that can change dynamically without code deploys.

The Python ecosystem is well-positioned for this architecture. FastMCP provides proxy primitives with session isolation and namespace management. ContextForge demonstrates production patterns for async database access, session pooling, and credential encryption. Cerbos and OPA provide sub-millisecond policy decisions. The remaining work for CommandClaw-MCP is composing these proven components into a cohesive gateway, not inventing new primitives.

---

## References

[1] Model Context Protocol Authors. "Transports - Model Context Protocol Specification (2025-11-25)." *modelcontextprotocol.io*. 2025-11-25. URL: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports.

[2] fka.dev. "Why MCP Deprecated SSE and Went with Streamable HTTP." *blog.fka.dev*. 2025-06-06. URL: https://blog.fka.dev/blog/2025-06-06-why-mcp-deprecated-sse-and-go-with-streamable-http/.

[3] MCPcat. "MCP Transport Protocols: stdio vs SSE vs StreamableHTTP." *mcpcat.io*. URL: https://mcpcat.io/guides/comparing-stdio-sse-streamablehttp/.

[4] Model Context Protocol Authors. "Lifecycle - Model Context Protocol Specification (2025-11-25)." *modelcontextprotocol.io*. 2025-11-25. URL: https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle.

[5] Portkey. "MCP Message Types: Complete MCP JSON-RPC Reference Guide." *portkey.ai*. URL: https://portkey.ai/blog/mcp-message-types-complete-json-rpc-reference-guide/.

[6] Model Context Protocol Authors. "Transports - Model Context Protocol Specification (2024-11-05)." *modelcontextprotocol.io*. 2024-11-05. URL: https://modelcontextprotocol.io/specification/2024-11-05/basic/transports.

[8] Bright Data. "SSE vs Streamable HTTP: Why MCP Switched Transport Protocols." *brightdata.com*. URL: https://brightdata.com/blog/ai/sse-vs-streamable-http.

[9] Composio. "MCP Gateways: A Developer's Guide to AI Agent Architecture in 2026." *composio.dev*. 2026. URL: https://composio.dev/content/mcp-gateways-guide.

[10] Microsoft. "microsoft/mcp-gateway: MCP Gateway -- reverse proxy and management layer for MCP servers." *GitHub*. 2025. URL: https://github.com/microsoft/mcp-gateway.

[11] Microsoft. "MCP Gateway Documentation." *microsoft.github.io*. 2025. URL: https://microsoft.github.io/mcp-gateway/.

[12] Docker. "MCP Gateway." *Docker Docs*. 2026. URL: https://docs.docker.com/ai/mcp-catalog-and-toolkit/mcp-gateway/.

[13] Docker. "docker/mcp-gateway: docker mcp CLI plugin / MCP Gateway." *GitHub*. 2026. URL: https://github.com/docker/mcp-gateway.

[14] Envoy Proxy. "Announcing Model Context Protocol Support in Envoy AI Gateway." *aigateway.envoyproxy.io*. 2025. URL: https://aigateway.envoyproxy.io/blog/mcp-implementation/.

[15] Envoy Proxy. "The Reality and Performance of MCP Traffic Routing with Envoy AI Gateway." *aigateway.envoyproxy.io*. 2025. URL: https://aigateway.envoyproxy.io/blog/mcp-in-envoy-ai-gateway/.

[16] IBM. "ContextForge AI Gateway." *ibm.github.io*. 2025. URL: https://ibm.github.io/mcp-context-forge/.

[17] Agentic Community. "mcp-gateway-registry: Enterprise-ready MCP Gateway & Registry." *GitHub*. 2025. URL: https://github.com/agentic-community/mcp-gateway-registry.

[18] LiteLLM. "MCP Overview." *docs.litellm.ai*. 2025. URL: https://docs.litellm.ai/docs/mcp.

[19] sparfenyuk. "mcp-proxy: A bridge between Streamable HTTP and stdio MCP transports." *GitHub / PyPI*. 2025. URL: https://pypi.org/project/mcp-proxy/.

[20] FastMCP. "MCP Proxy Provider." *gofastmcp.com*. 2025. URL: https://gofastmcp.com/servers/providers/proxy.

[21] Amartya Dev. "Building a Dynamic MCP Proxy Server in Python." *DEV Community*. 2025. URL: https://dev.to/amartyadev/building-a-dynamic-mcp-proxy-server-in-python-16jf.

[22] AWS. "aws/mcp-proxy-for-aws: AWS MCP Proxy Server." *GitHub*. 2025. URL: https://github.com/aws/mcp-proxy-for-aws.

[23] Ilya Grigorik. "MCProxy: MCP proxy -- tool aggregation, search, filtering, security." *GitHub*. 2025. URL: https://github.com/igrigorik/MCProxy.

[25] Red Hat. "Advanced authentication and authorization for MCP Gateway." *Red Hat Developer*. 2025-12-12. URL: https://developers.redhat.com/articles/2025/12/12/advanced-authentication-authorization-mcp-gateway.

[26] Zuplo. "API Key Rotation and Lifecycle Management: Zero-Downtime Strategies." *Zuplo Learning Center*. URL: https://zuplo.com/learning-center/api-key-rotation-lifecycle-management.

[27] API Stronghold. "Rotating API Keys Won't Save You (Here's What Will)." *API Stronghold Blog*. URL: https://www.apistronghold.com/blog/rotating-api-keys-wont-save-you.

[28] Traceable AI. "Dizzy Keys: Why API Key Rotation Matters." *Traceable Blog*. URL: https://www.traceable.ai/blog-post/dizzy-keys-why-api-key-rotation-matters.

[29] Flanagan. "Token Lifetimes and Security in OAuth 2.0: Best Practices and Emerging Trends." *IDPro Body of Knowledge*. URL: https://bok.idpro.org/article/id/108/.

[30] OneUptime. "How to Create API Key Rotation." *OneUptime Blog*. 2026-01-30. URL: https://oneuptime.com/blog/post/2026-01-30-api-key-rotation/view.

[31] HashiCorp. "Rotated vs. Dynamic Secrets: Which Should You Use?" *HashiCorp Blog*. URL: https://www.hashicorp.com/en/blog/rotated-vs-dynamic-secrets-which-should-you-use.

[34] R. Spletzer. "Zero to Trusted: SPIFFE and SPIRE, Demystified." *spletzer.com*. 2025-03. URL: https://www.spletzer.com/2025/03/zero-to-trusted-spiffe-and-spire-demystified/.

[35] ArXiv. "Establishing Workload Identity for Zero Trust CI/CD: From Secrets to SPIFFE-Based Authentication." *arxiv.org*. 2025. URL: https://arxiv.org/html/2504.14760v1.

[36] AWS. "AssumeRole - AWS Security Token Service." *AWS Documentation*. URL: https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRole.html.

[38] API Stronghold. "The Phantom Token Pattern, but for Production AI Agents." *API Stronghold Blog*. URL: https://www.apistronghold.com/blog/phantom-token-pattern-production-ai-agents.

[41] Oso. "Why RBAC is Not Enough for AI Agents." *osohq.com*. 2025. URL: https://www.osohq.com/learn/why-rbac-is-not-enough-for-ai-agents.

[42] Oso. "RBAC vs ABAC vs PBAC: Understanding Access Control Models in 2025." *osohq.com*. 2025. URL: https://www.osohq.com/learn/rbac-vs-abac-vs-pbac.

[43] Permit.io. "Permit MCP Gateway | Drop-in Trust for AI Agents." *permit.io*. 2025-2026. URL: https://www.permit.io/mcp-gateway.

[44] Ganie, A.G. "Securing AI Agents: Implementing Role-Based Access Control for Industrial Applications." *arXiv*. 2025-09-14. URL: https://arxiv.org/abs/2509.11431.

[46] Model Context Protocol. "Authorization - Model Context Protocol (Draft Specification)." *modelcontextprotocol.io*. 2025. URL: https://modelcontextprotocol.io/specification/draft/basic/authorization.

[47] WorkOS. "MCP 2025-11-25 is here: async Tasks, better OAuth, extensions, and a smoother agentic future." *workos.com*. 2025-11-25. URL: https://workos.com/blog/mcp-2025-11-25-spec-update.

[48] Parecki, A. "Client Registration and Enterprise Management in the November 2025 MCP Authorization Spec." *aaronparecki.com*. 2025-11-25. URL: https://aaronparecki.com/2025/11/25/1/mcp-authorization-spec-update.

[49] Model Context Protocol. "Tools - Model Context Protocol (Specification 2025-06-18)." *modelcontextprotocol.io*. 2025-06-18. URL: https://modelcontextprotocol.io/specification/2025-06-18/server/tools.

[50] CodiLime. "MCP server security: JWT authentication, scope-based authorization, and tool-level access control for network automation." *codilime.com*. 2025. URL: https://codilime.com/blog/mcp-server-security-for-network-automation/.

[51] Cerbos. "MCP Permissions. Securing AI Agent Access to Tools." *cerbos.dev*. 2025. URL: https://www.cerbos.dev/blog/mcp-permissions-securing-ai-agent-access-to-tools.

[54] Stacklok. "Introducing Virtual MCP Server: Unified gateway for multi-MCP workflows." *stacklok.com*. 2025-2026. URL: https://stacklok.com/blog/introducing-virtual-mcp-server-unified-gateway-for-multi-mcp-workflows/.

[55] Masani, P.J. "MCP Delegation Gateway: Verifiable Least-Privilege for AI Agents." *Medium*. 2026-02. URL: https://prabhakaranjm.medium.com/mcp-delegation-gateway-verifiable-least-privilege-for-ai-agents-d5b5fe3cf6da.

[60] Jared Lowin. "What's New in FastMCP 3.0." *jlowin.dev*. 2025. URL: https://www.jlowin.dev/blog/fastmcp-3-whats-new.

[61] DeepWiki. "AggregateProvider and Component Namespacing | jlowin/fastmcp." *deepwiki.com*. 2025. URL: https://deepwiki.com/jlowin/fastmcp/4.3-token-management-and-verification.

[62] PrefectHQ/fastmcp. "src/fastmcp/server/providers/proxy.py." *GitHub*. 2025. URL: https://github.com/jlowin/fastmcp/blob/main/src/fastmcp/server/providers/proxy.py.

[63] Jared Lowin. "MCP Proxy Servers with FastMCP 2.0." *jlowin.dev*. 2025. URL: https://www.jlowin.dev/blog/fastmcp-proxy.

[64] Alex Retana. "Streamlining MCP Management: Bundle Multiple Servers with FastMCP Proxies." *DEV Community*. 2025. URL: https://dev.to/alexretana/streamlining-mcp-management-bundle-multiple-servers-with-fastmcp-proxies-n3i.

[65] FastMCP. "Composing Servers." *gofastmcp.com*. 2025. URL: https://gofastmcp.com/servers/composition.

[66] FastMCP. "Bearer Token Authentication." *gofastmcp.com*. 2025. URL: https://gofastmcp.com/clients/auth/bearer.

[67] FastMCP. "Middleware." *gofastmcp.com*. 2025. URL: https://gofastmcp.com/servers/middleware.

[68] Manu Francis. "Your AI Agent is Leaking Secrets to LLMs When Calling MCP Tools: Fix It with Secure Context Passing." *Medium*. 2025. URL: https://medium.com/@manuedavakandam/your-ai-agent-is-leaking-secrets-to-llms-when-calling-mcp-tools-fix-it-with-secure-context-passing-0da1ce072cd3.

[69] Amartya Dev. "Building a Dynamic MCP Proxy Server in Python." *DEV Community*. 2025. URL: https://dev.to/amartyadev/building-a-dynamic-mcp-proxy-server-in-python-16jf.

[76] IBM. "[BUG][DB]: Connection pool exhaustion -- sessions held during upstream HTTP calls. Issue #1706." *GitHub: IBM/mcp-context-forge*. 2025. URL: https://github.com/IBM/mcp-context-forge/issues/1706.

[77] IBM. ".env.example and Configuration Reference." *ContextForge AI Gateway Documentation*. 2025. URL: https://ibm.github.io/mcp-context-forge/manage/configuration/.

[78] IBM. "config.py -- MCP Session Pool Settings." *GitHub: IBM/mcp-context-forge*. 2025. URL: https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/config.py.

[79] IBM. "README.md." *GitHub: IBM/mcp-context-forge*. 2025. URL: https://github.com/IBM/mcp-context-forge.

[80] IBM. "Releases." *GitHub: IBM/mcp-context-forge*. 2025-2026. URL: https://github.com/IBM/mcp-context-forge/releases.

[82] IBM. "Observability." *ContextForge AI Gateway Documentation*. 2025. URL: https://ibm.github.io/mcp-context-forge/manage/observability/.

[84] IBM. "[TESTING][SECURITY]: Encryption and secrets manual test plan (Argon2, Fernet, key derivation). Issue #2405." *GitHub: IBM/mcp-context-forge*. 2026. URL: https://github.com/IBM/mcp-context-forge/issues/2405.

[86] Nordic APIs. "Understanding The Phantom Token Approach." *Nordic APIs*. URL: https://nordicapis.com/understanding-the-phantom-token-approach/.

[87] Curity. "Securing APIs with The Phantom Token Approach." *Curity*. URL: https://curity.io/resources/learn/phantom-token-pattern/.

[88] nono. "Credential Protection for AI Agents: The Phantom Token Pattern." *nono.sh*. URL: https://nono.sh/blog/blog-credential-injection.

[89] API Stronghold. "The Phantom Token Pattern, but for Production AI Agents." *API Stronghold*. URL: https://www.apistronghold.com/blog/phantom-token-pattern-production-ai-agents.

[90] Solo.io. "MCP Authorization Patterns for Upstream API Calls." *Solo.io*. URL: https://www.solo.io/blog/mcp-authorization-patterns-for-upstream-api-calls.

[91] Python Software Foundation. "secrets -- Generate secure random numbers for managing secrets." *Python Docs*. URL: https://docs.python.org/3/library/secrets.html.

[92] OneUptime. "How to Secure APIs with HMAC Signing in Python." *OneUptime Blog*. 2026-01-22. URL: https://oneuptime.com/blog/post/2026-01-22-hmac-signing-python-api/view.

[93] GitGuardian. "HMAC Secrets Explained: Authentication You Can Actually Implement." *GitGuardian Blog*. URL: https://blog.gitguardian.com/hmac-secrets-explained-authentication/.

[94] Luke Hinds. "nono-networking-credential-design.md." *GitHub Gist*. URL: https://gist.github.com/lukehinds/9346514519b5c7a3047de5a0b0e083ae.

[95] Microsoft. "Rotation tutorial for resources with two sets of credentials." *Microsoft Learn*. 2026-03-26. URL: https://learn.microsoft.com/en-us/azure/key-vault/secrets/tutorial-rotation-dual.

[96] Zuplo. "API Key Rotation and Lifecycle Management: Zero-Downtime Strategies." *Zuplo*. URL: https://zuplo.com/learning-center/api-key-rotation-lifecycle-management.

[98] better-auth. "Refresh Token Rotation Grace Period (Overlap Window) -- Issue #8512." *GitHub*. URL: https://github.com/better-auth/better-auth/issues/8512.

[100] Red Hat. "Advanced authentication and authorization for MCP Gateway." *Red Hat Developer*. 2025-12-12. URL: https://developers.redhat.com/articles/2025/12/12/advanced-authentication-authorization-mcp-gateway.

[101] Model Context Protocol. "Security Best Practices." *modelcontextprotocol.io*. URL: https://modelcontextprotocol.io/specification/draft/basic/security_best_practices.

[103] Envoy AI Gateway Project. "The Reality and Performance of MCP Traffic Routing with Envoy AI Gateway." *Envoy AI Gateway Blog*. 2025. URL: https://aigateway.envoyproxy.io/blog/mcp-in-envoy-ai-gateway/.

[104] Envoy AI Gateway Project. "Announcing Model Context Protocol Support in Envoy AI Gateway." *Envoy AI Gateway Blog*. 2025. URL: https://aigateway.envoyproxy.io/blog/mcp-implementation/.

[105] Envoy AI Gateway Contributors. "ai-gateway: internal/mcpproxy/crypto.go, internal/mcpproxy/session.go." *GitHub (envoyproxy/ai-gateway)*. 2025-2026. URL: https://github.com/envoyproxy/ai-gateway/pull/1260.

[106] Tetrate. "Envoy AI Gateway MCP Performance." *Tetrate Blog*. 2025. URL: https://tetrate.io/blog/envoy-ai-gateway-mcp-performance.

[107] Envoy AI Gateway Project. "Helm Chart values.yaml (mcp.sessionEncryption)." *GitHub (envoyproxy/ai-gateway)*. 2025-2026. URL: https://github.com/envoyproxy/ai-gateway/blob/main/manifests/charts/ai-gateway-helm/values.yaml.

[108] Envoy AI Gateway Project. "Model Context Protocol (MCP) Gateway Documentation." *Envoy AI Gateway Docs*. 2026. URL: https://aigateway.envoyproxy.io/docs/capabilities/mcp/.

[109] LangChain. "Model Context Protocol (MCP) - Docs by LangChain." *LangChain Documentation*. 2026. URL: https://docs.langchain.com/oss/python/langchain/mcp.

[111] Cerbos. "cerbos-mcp-authorization-demo." *GitHub*. 2025. URL: https://github.com/cerbos/cerbos-mcp-authorization-demo.

[112] Cerbos. "Dynamic Authorization for AI Agents. A Guide to Fine-Grained Permissions in MCP Servers." *cerbos.dev*. 2025. URL: https://www.cerbos.dev/blog/dynamic-authorization-for-ai-agents-guide-to-fine-grained-permissions-mcp-servers.

[113] Model Context Protocol. "Using notifications/tools/list_changed." *GitHub Discussions*. 2025. URL: https://github.com/orgs/modelcontextprotocol/discussions/76.

[114] Cerbos. "Conditions." *Cerbos Documentation*. 2025. URL: https://docs.cerbos.dev/cerbos/latest/policies/conditions.html.

[115] Cerbos. "cerbos-sdk-python." *GitHub*. 2025. URL: https://github.com/cerbos/cerbos-sdk-python.

[116] Cerbos. "Enterprise-Grade Authorization for MCP Servers." *Cerbos*. 2025. URL: https://www.cerbos.dev/features-benefits-and-use-cases/dynamic-authorization-for-MCP-servers.

[117] Open Policy Agent. "Open Policy Agent Documentation." *openpolicyagent.org*. 2025. URL: https://www.openpolicyagent.org/docs.

[118] Open Policy Agent. "Integrating OPA." *openpolicyagent.org*. 2025. URL: https://www.openpolicyagent.org/docs/integration.

[121] Turall. "OPA-python-client." *GitHub*. 2024. URL: https://github.com/Turall/OPA-python-client.

[122] Cerbos. "Cerbos vs. OPA." *Cerbos Blog*. 2025. URL: https://www.cerbos.dev/blog/cerbos-vs-opa.

[123] Open Policy Agent. "Policy Performance." *openpolicyagent.org*. 2025. URL: https://www.openpolicyagent.org/docs/policy-performance.

[124] Cerbos. "MCP Permissions: Securing AI Agent Access to Tools." *Cerbos Blog*. 2025. URL: https://www.cerbos.dev/blog/mcp-permissions-securing-ai-agent-access-to-tools.
