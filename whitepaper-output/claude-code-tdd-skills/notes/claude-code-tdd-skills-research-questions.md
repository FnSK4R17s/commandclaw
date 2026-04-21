# Claude Code TDD Skills — Research Questions

<!-- Research questions for the Claude Code TDD Skills topic. -->
<!-- See .agents/skills/beary/skills/internet-research/SKILL.md for research workflow and guidelines. -->

**Topic description:** How to set up AI-coding-agent automation (Claude Code Skills, OpenAI Codex configuration, and comparable harnesses) to enforce or encourage test-driven development (TDD) workflows. Covers skill authoring patterns, hooks/guardrails, subagent orchestration, prompt design for red-green-refactor cycles, and the broader landscape of TDD-in-AI tooling.

**Purpose:** (a) Decide which enforcement pattern fits — soft skill guidance vs. hook-enforced vs. subagent pair; (b) produce a drop-in TDD skill for Claude Code; (c) broad survey of how Claude Code, OpenAI Codex, and other AI coding agents are wiring TDD.

## General Understanding

### Q1: What are the canonical patterns for authoring a Claude Code Skill, and what are the equivalent customization primitives in OpenAI Codex?

**Search terms:**
- Claude Code skill authoring SKILL.md frontmatter conventions
- OpenAI Codex CLI AGENTS.md custom instructions configuration
- Claude Code hooks PreToolUse PostToolUse reference

### Q2: How do AI coding agents currently support test-driven development workflows, and what guidance exists from vendors?

**Search terms:**
- Anthropic Claude Code test-driven development guide
- OpenAI Codex TDD red green refactor prompt
- AI coding agent TDD workflow best practices 2025 2026

### Q3: What community-contributed TDD skills, commands, or subagents already exist for Claude Code and similar agents?

**Search terms:**
- Claude Code TDD skill GitHub repository
- awesome-claude-code skills test driven development
- claude code subagent test runner pytest jest

### Q4: Across the broader AI coding agent ecosystem (Cursor, Aider, Cline, Copilot Workspace, Windsurf), how is TDD operationalized, and what lessons transfer?

**Search terms:**
- Aider test driven development --test-cmd
- Cursor rules TDD workflow
- Cline Copilot Workspace test first development AI agent

---

## Deeper Dive

### Subtopic A — Enforcement Pattern Design

#### A1: How do the three enforcement patterns (soft skill, hook-enforced, subagent pair) compare on reward-hacking resistance, cost, and developer friction, and what hybrid combinations are empirically best?

**Search terms:**
- Claude Code hook vs skill vs subagent TDD enforcement comparison
- tdd-guard cost overhead PostToolUse LLM validation
- reward hacking mitigation TDD AI agent 2026

#### A2: What is the failure mode taxonomy when AI agents attempt TDD, and what structural defenses actually work?

**Search terms:**
- AI coding agent test tampering mitigation filesystem permissions
- SWE-bench reward hacking conftest.py 2026 defense
- read-only test files agent sandbox containment

#### A3 (Purpose-driven): Given the goal of producing a drop-in TDD skill, what hybrid architecture gives the best quality-per-token across pytest/jest/go/rust?

**Search terms:**
- hybrid TDD skill hook prompt subagent architecture Claude Code
- language-agnostic test runner adapter AI agent
- deterministic TDD phase state machine coding agent

---

### Subtopic B — Authoring a Drop-in Claude Code TDD Skill

#### B1: What concrete SKILL.md frontmatter, body structure, and supporting files characterize a high-quality TDD skill, and what anti-patterns does the skill-creator meta-skill flag?

**Search terms:**
- Claude Code skill-creator best practices SKILL.md structure
- progressive disclosure skill design Anthropic Agent Skills
- SKILL.md description trigger keywords accuracy

#### B2: How should a TDD skill persist red/green/refactor phase state across tool calls, and what options exist (file-based, hook-shared, memory)?

**Search terms:**
- Claude Code session state persistence skill memory
- TDD phase state machine file-based Claude skill
- PostToolUse hook shared state session_id

#### B3 (Purpose-driven): What does a language-adapter layer look like for pytest, jest/vitest, go test, and cargo test, and how do the tdd-guard reporter packages inform the design?

**Search terms:**
- tdd-guard reporter architecture pytest jest vitest
- multi-language test runner AI agent adapter 2026
- structured test output parser LLM feedback

---

### Subtopic C — Cross-Harness Portability (Claude Code + OpenAI Codex)

#### C1: What portable contract works across Claude Code and OpenAI Codex without losing the enforcement benefits of Claude Code's hooks?

**Search terms:**
- agent skills standard portable SKILL.md Codex Claude
- AGENTS.md CLAUDE.md dual authoring convention
- cross-agent TDD workflow portability 2026

#### C2: How do projects that ship TDD workflows for multiple harnesses (superpowers, Aider, specmint-tdd) handle the "hooks-in-Claude but not Codex" asymmetry?

**Search terms:**
- superpowers AGENTS.md Codex Claude Code cross compat
- Aider vs Claude Code TDD portability comparison
- multi-harness AI agent TDD project template

---

## Redundant Questions

<!-- Move any redundant questions here during review. -->
