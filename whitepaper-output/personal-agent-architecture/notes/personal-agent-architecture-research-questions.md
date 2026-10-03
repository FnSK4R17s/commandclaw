# personal-agent-architecture — Research Questions

<!-- Research questions for the personal-agent-architecture topic. -->
<!-- Mode: HYPERPHAGIA. Review flow: UNATTENDED. -->
<!-- Purpose: reference whitepaper to inform development of CommandClaw (git-native OpenClaw redesign at /apps/commandclaw*). -->

## General Understanding

### Q1: What is OpenClaw — origin, lineage (Clawdbot → Moltbot → OpenClaw), creator, adoption, and what does it actually do?

**Search terms:**
- OpenClaw personal AI agent what is it
- Clawdbot Moltbot OpenClaw Peter Steinberger history rename
- OpenClaw adoption users 2026

### Q2: What is OpenClaw's core runtime architecture — gateway/daemon, session model, agent loop, model providers?

**Search terms:**
- OpenClaw gateway architecture documentation
- OpenClaw session model agent loop concepts
- OpenClaw docs architecture overview

### Q3: How does OpenClaw implement memory and persona — SOUL.md, IDENTITY.md, MEMORY.md, daily notes, workspace files, compaction?

**Search terms:**
- OpenClaw SOUL.md MEMORY.md workspace memory files
- OpenClaw agent memory daily notes compaction
- file-based markdown memory AI agent pattern

### Q4: What is OpenClaw's security model and what are its documented failures (vulnerability counts, exposed instances, incidents)?

**Search terms:**
- OpenClaw security vulnerabilities exposed instances research
- OpenClaw exposed gateways shodan censys report
- OpenClaw prompt injection malware skills incident

---

## Deeper Dive

### Subtopic A: Autonomy & scheduling (the proactive engine)
#### Q1: How do heartbeat, cron, webhooks, and hooks actually work, and how is proactive autonomy kept safe?
**Search terms:** OpenClaw heartbeat cron proactive tasks; OpenClaw hooks webhooks automation; agent scheduled tasks safety confirmation

### Subtopic B: Skills/plugin ecosystem & MCP
#### Q1: What is the skill/plugin format, how does ClawHub distribute them, and how does MCP fit?
**Search terms:** OpenClaw skills format ClawHub plugin; OpenClaw MCP model context protocol support; Claude Agent Skills format markdown SKILL.md

### Subtopic C: Comparable systems (competitive landscape)
#### Q1: How do Letta/MemGPT-style memory agents differ from file-based vault agents?
**Search terms:** Letta MemGPT memory architecture agent; MemGPT vs file-based memory agent; stateful agent memory blocks
#### Q2: How do Claude Code / AGENTS.md vault agents and other personal-agent frameworks compare?
**Search terms:** Claude Code AGENTS.md vault agent pattern; personal AI agent frameworks comparison 2026; git-native agent control plane

### Subtopic D: Security hardening patterns for agent gateways
#### Q1: What are the established patterns for credential isolation and tool-call mediation (phantom tokens, proxies, RBAC)?
**Search terms:** phantom token pattern API credential proxy; MCP gateway RBAC Cerbos agent security; AI agent credential isolation broker pattern

---

## Redundant Questions

<!-- Move any redundant questions here during review. -->
