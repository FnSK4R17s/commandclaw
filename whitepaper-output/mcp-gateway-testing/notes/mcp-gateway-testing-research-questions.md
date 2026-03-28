# MCP Gateway Testing — Research Questions

## General Understanding

### Q1: How do FastMCP and mcp-proxy projects test their MCP protocol implementations, and what testing patterns do they use for proxy/gateway behavior?

**Search terms:**
- FastMCP pytest test suite proxy middleware testing
- mcp-proxy Python testing strategy MCP protocol compliance
- MCP SDK test patterns JSON-RPC proxy server Python

### Q2: What are the established patterns for testing async Python security middleware (HMAC verification, token authentication, RBAC enforcement) in FastAPI applications?

**Search terms:**
- FastAPI async middleware testing HMAC token authentication pytest
- Python async security middleware testing patterns RBAC enforcement
- pytest-asyncio ASGI middleware testing authentication authorization

### Q3: How do you set up integration tests for MCP servers, including testing stdio transport bridging, Streamable HTTP, and session management?

**Search terms:**
- MCP server integration testing stdio HTTP transport Python
- Model Context Protocol testing session management Streamable HTTP
- testing MCP tools/list tools/call JSON-RPC 2.0 Python end-to-end

### Q4: What are the best practices for testing credential encryption, token rotation, circuit breakers, and Redis-backed session stores in Python async applications?

**Search terms:**
- testing Fernet Argon2id credential encryption Python pytest
- fakeredis pytest-asyncio session store rate limiter testing
- circuit breaker testing Python async session pool token rotation

---

## Deeper Dive

### Subtopic 1: MCP Protocol Compliance Testing

#### Q1: What specific protocol constraints (message ID preservation, notification passthrough, capability negotiation, SSE resumability) need automated verification in an MCP gateway?

**Search terms:**
- MCP specification protocol compliance testing JSON-RPC message ID preservation
- MCP SSE resumability Last-Event-ID testing server-sent events proxy
- MCP capability negotiation Initialize handshake automated testing

#### Q2: How do existing MCP testing tools (MCP Inspector, mcp-test) work, and can they be used to validate a custom gateway?

**Search terms:**
- MCP Inspector testing tool protocol validation 2025
- mcp-test MCP compliance testing framework
- MCP server testing tools automated validation protocol

### Subtopic 2: Security Layer Testing

#### Q3: How should phantom token patterns, HMAC-signed requests, and dual-key rotation be tested to verify security properties like constant-time comparison and replay prevention?

**Search terms:**
- testing HMAC constant-time comparison timing attack prevention Python
- phantom token pattern testing credential isolation proxy gateway
- dual-key rotation testing overlap window token revocation verification

#### Q4: What testing approaches verify deny-by-default RBAC behavior, Cerbos policy evaluation, and rate limiting under concurrent load?

**Search terms:**
- Cerbos RBAC testing Python deny-by-default policy evaluation
- testing rate limiting Redis concurrent load pytest-asyncio
- RBAC dual-layer enforcement testing discovery filtering call guard

### Subtopic 3: Integration and End-to-End Testing

#### Q5: How do you build a test harness with stub MCP servers (both stdio and HTTP) for gateway integration testing?

**Search terms:**
- stub MCP server testing Python FastMCP test fixtures
- testing stdio subprocess proxy Python pytest integration
- mock MCP server HTTP SSE testing gateway proxy end-to-end

#### Q6: What Docker Compose test environments are used for testing gateways with Redis, Cerbos PDP, and upstream MCP servers?

**Search terms:**
- Docker Compose integration testing Redis Cerbos pytest Python
- gateway proxy integration test environment Docker MCP server
- testcontainers Python Redis Cerbos async integration testing

---

## Redundant Questions

