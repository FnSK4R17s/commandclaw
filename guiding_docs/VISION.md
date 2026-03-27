# Command Claw

## Vision

Command Claw is a Git-native agent platform built for enterprise reliability and control. It is a ground-up redesign of the autonomous AI agent experience — solving the architectural failures of OpenClaw while preserving the core value proposition of persistent, background-running agents.

## Problem

OpenClaw — the fastest-growing open-source agent project in GitHub history — has fundamental architectural problems that make it unsuitable for serious use:

- **State and context loss.** Agents forget critical information (credentials, configuration, prior instructions) between interactions. Users are forced to repeatedly remind the agent of things it should already know.
- **Opaque interaction model.** The only interface is chat (Telegram, Slack, Discord). There is no way to directly inspect agent state, edit configuration, or debug failures without asking the agent to fix itself — which it often can't.
- **Unreliable task execution.** Scheduled tasks (cron jobs, reminders) fail intermittently with no visibility into why.
- **No MCP support.** Agents interact with external tools via ad-hoc API calls rather than structured, authenticated protocol boundaries. This creates unpredictable behavior and security exposure.
- **Poor documentation.** Setup, credential management, and troubleshooting are poorly documented, making it difficult to operate or extend.
- **Massive attack surface.** 512 vulnerabilities found in early audit. 135K+ instances exposed publicly. Skills are arbitrary code directories with no enforcement or vetting.
- **Tech debt from agent-first development.** OpenClaw was built by AI agents without proper upfront architecture, resulting in a fragile and hard-to-maintain codebase.

The root cause: OpenClaw optimized for approachability (chat-first, consumer-friendly) at the expense of control, reliability, and auditability — the things enterprise users actually need.

## Core Insight

The agent's vault — not chat — should be the control plane. Configuration, memory, behavior rules, and skills should live in files you can directly inspect, edit, version, and audit. Chat (Telegram) is the I/O layer, not the management interface.

## Architecture

### Three Layers

**1. Agent Runtime**

- Built on LangChain with OpenAI as the LLM provider.
- Single execution loop shared across all agents — agents differ only by prompt and vault contents.
- Each agent runs independently with its own isolated Git repository as its vault.
- Vault contains:
  - `agents.md` — behavior configuration and system prompt.
  - Memory files — persistent state the agent reads and writes.
  - Skills folder — markdown files describing available capabilities.
- Agents read vault state at execution start, operate with loaded context, and write state back via Git commits.

**2. Skills Layer**

- Skills are markdown files in a known folder structure within the agent's vault.
- Agents scan the skills folder at runtime, read descriptions into context, and access full instructions on demand.
- Skills are installed and managed manually by administrators using Vercel's Skills CLI, pulling from GitHub repositories.
- Agents cannot install, update, or manage their own skills. They can only point users to the appropriate location for skill management.
- Validation scripts run when new skills are dropped into the folder to check structural correctness.
- If an agent identifies an improvement to a skill, it creates a GitHub issue on the skill's repository for the maintainer to review — using the same workflow humans use for code contributions.

**3. MCP Layer**

- MCP (Model Context Protocol) servers handle authentication-gated sensitive operations: credential access, deployments, protected API calls.
- Access control is enforced at the MCP server level. When an agent requests available tools, the MCP server returns only the tools that agent is authorized to use. Unauthorized tools are invisible.
- MCP protocol implementation is delegated to the Linux Foundation standard — Command Claw consumes MCP, it does not reimplement it.
- Skills handle general capabilities. MCP handles security boundaries. Clear separation of concerns.

### Key Design Decisions

- **Separate Git repos per agent vault.** Natural isolation at the Git permission level. Different people get access to different agents by controlling repo permissions. Access control inherits from Git.
- **Markdown-only for vault files.** Agents can corrupt structured formats like JSON. Markdown is forgiving, human-readable, and nearly impossible to break beyond usability.
- **Git as the audit trail.** Every state change is versioned and traceable. Git log and git diff provide a complete record of what changed, when, and by whom.
- **Langfuse for execution observability.** Every agent run is traced. Every tool call, MCP operation, and LLM invocation is logged and inspectable via the Langfuse dashboard.
- **Telegram as the I/O layer.** Deliberately simple. Agents receive instructions and send responses/alerts via Telegram. Telegram's API is stable, well-documented, and reliable.
- **Three retries with exponential backoff.** On failure, the agent retries up to three times. If all retries fail, the agent alerts its owner via Telegram with failure details.
- **Git-based recovery.** If an agent writes bad state, uncommitted changes are discarded and the agent resumes from the last known good commit. No complex checkpointing needed.
- **Agents read fresh on every access.** If a skill or configuration file changes mid-execution, the agent reads the new version. This is the pragmatic default — if you change files while an agent is running, that's on you.

## Scope

### Week One — Prototype

- Agent execution loop (LangChain + OpenAI).
- Telegram bot integration (input/output and failure alerts).
- Vault reading and writing (agents.md, memory files).
- Skill discovery and loading from folder structure.
- Langfuse integration for execution tracing.
- One working agent — the coding agent, as it exercises the most complex execution path.

### Week Two

- Proper job scheduler for reliable reminders and recurring tasks.
- Git-based resumability for failed executions.
- MCP server scaffolding and integration.
- Multi-tenant vault isolation patterns.

### Non-Scope

- **Cross-agent communication.** Agents do not talk to each other directly. If an agent discovers something useful, it creates a GitHub issue for the relevant skill or vault maintainer. Same workflow as human developers.
- **Skills package management.** Handled by Vercel's Skills CLI. Not reimplemented.
- **MCP protocol implementation.** Delegated to the Linux Foundation standard.
- **Cost optimization.** API costs are a business expense, not an engineering constraint.

## Positioning

Command Claw is agent infrastructure built for control and visibility. It exists because OpenClaw proved the demand for autonomous agents but failed on the architecture that enterprises require: auditability, reliability, direct configurability, and security boundaries.

The name says it: Command. You command your agents. They don't command you.