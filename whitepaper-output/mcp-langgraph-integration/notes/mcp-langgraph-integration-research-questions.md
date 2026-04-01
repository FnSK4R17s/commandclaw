# MCP-LangGraph Integration — Research Questions

## General Understanding

### Q1: How does LangChain/LangGraph officially integrate with MCP servers, and what async patterns does it use?

**Search terms:**
- LangChain MCP integration tools LangGraph
- langchain-mcp-adapters MCP tool wrapping
- LangGraph MCP server tools async pattern

### Q2: What is the anyio vs asyncio compatibility problem with MCP's streamable HTTP transport, and how have others solved it?

**Search terms:**
- MCP streamablehttp_client anyio asyncio conflict
- anyio cancel scope asyncio LangGraph compatibility
- MCP SDK anyio task group asyncio event loop conflict

### Q3: What patterns exist for running an anyio-based MCP connection in a separate thread alongside an asyncio application?

**Search terms:**
- anyio asyncio interop separate thread event loop
- MCP client dedicated thread asyncio wrapper
- run anyio coroutine from asyncio thread Python

### Q4: What alternative MCP transport options exist that avoid the anyio conflict (SSE, per-request HTTP)?

**Search terms:**
- MCP SSE transport vs streamable HTTP client Python
- MCP stateless HTTP transport per-request
- FastMCP client transport options Python SDK

---

## Deeper Dive

<!-- To be filled after General Understanding phase -->

---

## Redundant Questions

<!-- Move any redundant questions here during review. -->
