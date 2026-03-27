# User Context

This file contains user-specific context that customizes how the Background Research Agent (BEARY) conducts research.

## Audience

The research audience is an expert-level engineer and data scientist (Shikhar Shukla) who builds AI agent platforms (OpenClaw, CommandClaw, chakravarti-cli). Assume deep familiarity with Python, LangChain, MCP protocol, Docker, Git, and distributed systems architecture. Skip introductory explanations — go straight to implementation details, trade-offs, and edge cases.

## Purpose

Broad exploration of the topic space. Focus on architectural patterns, existing implementations, security models, and technical trade-offs rather than narrowing to a single solution prematurely.

## Priorities

When researching, prioritize:
- Official protocol specifications and standards documents (MCP spec, Linux Foundation)
- Academic literature and peer-reviewed security research
- Official documentation from established projects (LangChain, Anthropic, OpenAI)
- Reputable technical blogs from known organizations (Cloudflare, Vercel, Stripe engineering)
- GitHub repositories with significant traction (stars, forks, active maintenance)

Avoid sources from:
- Unknown blogs and unverified forums
- Marketing content disguised as technical writing
- Outdated documentation (>90 days for fast-moving topics like MCP)

## Freshness

For fast-moving topics, sources should be within the last 90 days.

## Depth and Skepticism

Prioritize deep technical detail over concise summaries. Contradiction checks should be strict — flag conflicting claims explicitly with source attribution.

## Research Mode

Default research mode controls token usage and depth.

- **Hibernation**: Token-conservative. Fewer questions and search terms, sufficiency checks enabled, subtopics only when clearly needed.
- **Hyperphagia**: Token-generous. More questions and search terms, no early stopping, subtopics encouraged.

<!-- RESEARCH_MODE: hyperphagia -->

## Review Flow

Default review flow controls whether BEARY pauses for user review at checkpoints.

- **Attended**: Pause at checkpoints for user review before proceeding.
- **Unattended**: Complete the entire workflow without stopping.

<!-- REVIEW_FLOW: unattended -->

## Output Path

Specify where completed whitepaper artifacts should be moved after the workflow completes.

DEFAULT_OUTPUT_PATH: whitepaper-output

<!-- OUTPUT_PATH: whitepaper-output -->
