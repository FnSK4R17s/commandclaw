# Command Claw — Vision (superseded)

> **This document is superseded.** It described an earlier, abandoned project: a Python/LangChain **enterprise** agent platform, written before the Rust rebuild and the CommandClaw↔CKRV split. It is kept only as a redirect — do not treat its contents as current.

The live direction is the greenfield Rust rebuild:

- **ADR-0001** — rebuild in Rust; agentic/deterministic split; thin MCP seam to CKRV. → [`../docs/adr/0001-rebuild-commandclaw-rust.md`](../docs/adr/0001-rebuild-commandclaw-rust.md)
- **ADR-0002** — M1 delegation slice + the tripwire. → [`../docs/adr/0002-m1-delegation-slice.md`](../docs/adr/0002-m1-delegation-slice.md)
- **ADR-0003** — agent state = version-controlled markdown (the one tenet inherited from this dead vision). → [`../docs/adr/0003-agent-state-version-controlled-markdown.md`](../docs/adr/0003-agent-state-version-controlled-markdown.md)
- **CONTEXT.md** — current glossary. → [`../CONTEXT.md`](../CONTEXT.md)
- **plan/M1-delegation-slice.md** — the active build plan. → [`../plan/M1-delegation-slice.md`](../plan/M1-delegation-slice.md)

The full prior text lives in git history (before this commit). One tenet — *agent state as version-controlled markdown files* — survived the cull and is now ADR-0003. Everything else here (enterprise positioning, the LangChain/OpenAI stack, the skills / Langfuse / RBAC scope) is dead or deferred.

## Historical artifacts

The preliminary whitepapers that informed this superseded design (RBAC, MCP-gateway, phantom-token proxy — now deferred or dropped), kept so they are not orphaned:

- [Agent Logic Refactor](../whitepaper-output/agent-logic-refactor/whitepaper/agent-logic-refactor-whitepaper.md)
- [Agent Memory Architecture](../whitepaper-output/agent-memory-architecture/whitepaper/agent-memory-architecture-whitepaper.md)
- [Agent Privilege Management](../whitepaper-output/agent-privilege-management/whitepaper/agent-privilege-management-whitepaper.md)
- [MCP Gateway Architecture](../whitepaper-output/mcp-gateway-architecture/whitepaper/mcp-gateway-architecture-whitepaper.md)
- [MCP Gateway Testing](../whitepaper-output/mcp-gateway-testing/whitepaper/mcp-gateway-testing-whitepaper.md)
- [MCP + LangGraph Integration](../whitepaper-output/mcp-langgraph-integration/whitepaper/mcp-langgraph-integration-whitepaper.md)
