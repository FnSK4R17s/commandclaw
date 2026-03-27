# MCP Gateway Architecture — Research Questions

## General Understanding

### Q1: How does the MCP protocol work at the transport level, and what are the differences between stdio, SSE, and Streamable HTTP transports?

**Search terms:**
- MCP Model Context Protocol transport stdio SSE HTTP 2025
- MCP protocol specification transport layer architecture
- Model Context Protocol streamable HTTP vs stdio comparison

### Q2: What existing MCP gateway/proxy implementations exist, and how do they handle credential management and multi-server aggregation?

**Search terms:**
- MCP gateway proxy implementation credential management 2025
- MCP server aggregation proxy Python
- Model Context Protocol proxy relay existing projects GitHub

### Q3: How do production systems implement rotating API key authentication for service-to-service communication, and what are the security trade-offs?

**Search terms:**
- rotating API key authentication service mesh pattern
- short-lived token rotation gateway proxy security
- API key rotation interval security trade-offs blast radius

### Q4: What RBAC models exist for controlling tool/API access in agent systems, and how do MCP servers implement tool visibility filtering?

**Search terms:**
- RBAC role-based access control AI agent tool access
- MCP server tool filtering access control per-agent
- agent platform tool authorization model patterns

---

## Deeper Dive

### Subtopic A: Python MCP Gateway Implementation

#### Q5: How do FastMCP's proxy primitives (ProxyProvider, create_proxy, mount) work internally, and how would you build a multi-server aggregation gateway on top of them with credential injection?

**Search terms:**
- FastMCP ProxyProvider create_proxy mount implementation Python
- FastMCP proxy server aggregation tutorial 2025
- FastMCP credential injection middleware pattern

#### Q6: How does IBM ContextForge implement its async Python MCP gateway (FastAPI + SQLAlchemy), and what can we learn from its session pooling, transport bridging, and OpenTelemetry integration?

**Search terms:**
- IBM ContextForge MCP gateway FastAPI architecture
- mcp-context-forge Python implementation session management
- ContextForge OpenTelemetry observability MCP proxy

### Subtopic B: Phantom Token + Key Rotation Implementation

#### Q7: How do you implement the phantom token pattern specifically for an MCP gateway — opaque rotating tokens to agents, real credentials in the proxy, with HMAC-signed requests and 5-minute overlap windows?

**Search terms:**
- phantom token pattern implementation proxy Python
- opaque token gateway credential proxy HMAC signing
- short-lived token rotation overlap window implementation

#### Q8: How does Envoy AI Gateway's token-encoded session architecture work in detail, and could this stateless pattern replace distributed session stores for an MCP proxy?

**Search terms:**
- Envoy AI Gateway MCP token-encoded session architecture
- Envoy MCP session ID encryption KDF stateless routing
- stateless session management MCP gateway proxy

### Subtopic C: Policy Engine Integration for Tool RBAC

#### Q9: How do Cerbos and OPA integrate with MCP servers for dynamic tool authorization, and what does a concrete policy definition look like for per-agent tool filtering with ABAC conditions?

**Search terms:**
- Cerbos MCP server integration tool authorization example
- OPA Rego policy MCP tool filtering per-agent
- dynamic tool authorization AI agent policy engine ABAC

---

## Redundant Questions

<!-- Move any redundant questions here during review. -->
