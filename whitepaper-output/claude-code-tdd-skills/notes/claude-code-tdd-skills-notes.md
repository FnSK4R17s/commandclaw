# Claude Code TDD Skills — Notes

<!-- Notes for the Claude Code TDD Skills topic. Organized by question, not source. -->
<!-- Citations are stored in whitepaper/claude-code-tdd-skills-references.md -->

## General Understanding

### Q1: What are the canonical patterns for authoring a Claude Code Skill, and what are the equivalent customization primitives in OpenAI Codex?

#### Claude Code Skill Anatomy

A skill lives under a named directory containing a required `SKILL.md` entrypoint and any number of optional supporting files [1]:

```
.claude/skills/<name>/
├── SKILL.md          # required
├── examples.md       # optional reference material
└── scripts/          # optional executables
```

Storage tiers in descending priority: enterprise managed settings > `~/.claude/skills/` (personal) > `.claude/skills/` (project) > `<plugin>/skills/` (plugin-namespaced) [1]. Plugin skills use a `plugin-name:skill-name` namespace to avoid collision. Skill directories are watched live; new skills appear without restart unless the top-level directory itself is new [1].

**SKILL.md frontmatter fields** (all optional except the directory name implicitly sets `name`) [1]:

| Field | Default | Notes |
|---|---|---|
| `name` | directory name | Lowercase, hyphens, max 64 chars; becomes the `/slash-command` |
| `description` | first paragraph | Primary signal for auto-invocation; truncated at 1,536 chars |
| `when_to_use` | — | Appended to `description` in listing |
| `argument-hint` | — | Autocomplete hint, e.g., `[issue-number]` |
| `disable-model-invocation` | `false` | Removes skill from context entirely |
| `user-invocable` | `true` | `false` hides from `/` menu but keeps model invocable |
| `allowed-tools` | — | Grants permission for listed tools while skill is active |
| `model` | session default | Override model per-skill |
| `effort` | inherits | `low`/`medium`/`high`/`xhigh`/`max` |
| `context` | — | `fork` runs skill in an isolated subagent context |
| `agent` | `general-purpose` | Which subagent type to use when `context: fork` |
| `hooks` | — | Lifecycle hooks scoped to this skill |
| `paths` | — | Glob patterns; auto-activate only when working with matching files |
| `shell` | `bash` | `powershell` for Windows inline commands |

The Agent Skills standard (published 2025-12-18 at agentskills.io) defines a portable subset (`name`, `description`) that travels across Claude.ai, Claude Code, Agent SDK, and Developer Platform [7]. Claude Code extends this with `context`, `agent`, `hooks`, `paths`, and invocation-control fields.

**Invocation modes.** Default-frontmatter skills appear in context at all times (description only; body lazy-loads). `disable-model-invocation: true` removes description from context; body loads only when user types `/name`. `user-invocable: false` keeps description in context but hides the slash command. After auto-compaction, Claude Code re-attaches the most recent invocation of each skill up to 5,000 tokens each, shared 25,000-token budget across all skills [1].

**Dynamic context injection.** The `` !`<command>` `` syntax executes shell commands before Claude sees the prompt; output replaces the placeholder. Multi-line variant uses ` ```! ` fenced blocks. Policy `"disableSkillShellExecution": true` blocks this for user/project/plugin sources [1]. String substitutions: `$ARGUMENTS`, `$ARGUMENTS[N]` / `$N` (0-indexed), `${CLAUDE_SESSION_ID}`, `${CLAUDE_SKILL_DIR}` [1].

#### Supporting Claude Code Primitives

**Slash commands (`.claude/commands/*.md`).** Legacy predecessor to skills. A `.claude/commands/deploy.md` and `.claude/skills/deploy/SKILL.md` are functionally identical; skills take precedence on name conflict. Commands support the same frontmatter. No deprecation plans [1].

**Subagents (`.claude/agents/*.md`).** Markdown files with YAML frontmatter; body becomes the system prompt [3]. Key frontmatter: `name`, `description` (required); `tools` (allowlist) / `disallowedTools` (denylist); `model` (alias, full ID, or `inherit`); `permissionMode` (`default`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions`, `plan`); `maxTurns`; `skills` (array pre-injected at full content, not lazy-loaded); `mcpServers`; `hooks`; `memory` (`user`/`project`/`local`); `isolation: worktree`; `background: true`; `initialPrompt`. Built-in: `Explore` (Haiku, read-only), `Plan` (inherits model, read-only), `general-purpose` (all tools). Plugin subagents cannot use `hooks`, `mcpServers`, or `permissionMode` [3].

**Hooks in `settings.json`.** Configured under `"hooks"` key [2]:

```json
{ "hooks": { "PreToolUse": [ { "matcher": "Bash|Edit", "hooks": [{ "type": "command", "command": "/path/script.sh" }] } ] } }
```

Full event inventory as of April 2026: session — `SessionStart` (matcher: `startup`/`resume`/`clear`/`compact`), `SessionEnd`; turn — `UserPromptSubmit`, `Stop`, `StopFailure`, `SubagentStop`, `SubagentStart`; tool — `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `PermissionDenied`; other — `Notification`, `PreCompact`/`PostCompact`, `CwdChanged`, `FileChanged`, `TaskCreated`, `TaskCompleted`, `ConfigChange`, `WorktreeCreate`/`WorktreeRemove`, `Elicitation`/`ElicitationResult`, `InstructionsLoaded` [2].

**Matcher syntax.** Letters/digits/`_`/`|` = exact or pipe-separated list; any other character = JavaScript regex. MCP tools match as `mcp__<server>__<tool>` [2].

**Exit codes.** `0`: success, stdout JSON parsed. `2`: blocking error — blocks tool call (PreToolUse), rejects prompt (UserPromptSubmit), prevents stopping (Stop), denies permission (PermissionRequest). Other non-zero: non-blocking, stderr shown in transcript [2].

**Stdin JSON.** All events receive `session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`, plus event-specific fields. PreToolUse adds `tool_name`, `tool_input`, `tool_use_id`. PostToolUse adds `tool_response`. Subagent events add `agent_id`, `agent_type` [2].

**Decision output.** PreToolUse uses `hookSpecificOutput.permissionDecision` (`allow`/`deny`/`ask`/`defer`) — top-level `decision` is deprecated. `defer` only works in non-interactive mode (`-p`). `updatedInput` mutates tool arguments before execution; `additionalContext` injects context into the next turn [2].

**Hook handler types.** `command` (shell script), `http` (POST with optional headers/env-var allowlist), `prompt` (model prompt), `agent` (full subagent). Each supports `if` (permission-rule filter), `timeout`, `statusMessage`, `once` [2]. Hook scoping: global (`~/.claude/settings.json`), project (`.claude/settings.json`), project-local (`.claude/settings.local.json`), managed (org-wide), plugin (`hooks/hooks.json`), skill/agent frontmatter `hooks` field [2].

**CLAUDE.md memory.** Hierarchical instruction files loaded into system prompt context. Path-specific rules apply to `paths`-scoped content [1].

#### OpenAI Codex Equivalents

**AGENTS.md.** Primary customization primitive — Codex reads this before any work begins [4]. Resolution order per directory level: `AGENTS.override.md` → `AGENTS.md` → `project_doc_fallback_filenames` (default: `["TEAM_GUIDE.md", ".agents.md"]`). Files concatenate from repo root down to CWD; closer files take precedence. Global: `~/.codex/AGENTS.md` (or `AGENTS.override.md` for temporary override). `CODEX_HOME` env var overrides `~/.codex` location. AGENTS.md is free-form markdown — no typed frontmatter schema. Typical content: test commands, dependency conventions, code style, workflow commands [4][8].

**Config (`~/.codex/config.toml`).** Controls `project_doc_fallback_filenames`, `project_doc_max_bytes` (default 32 KiB, max 65 KiB) [5].

**Approval and sandbox controls.** CLI flags, not config primitives [6]: `--ask-for-approval / -a` (`untrusted | on-request | never`); `--sandbox / -s` (`read-only | workspace-write | danger-full-access`); `--full-auto` (`on-request` + `workspace-write`); `--dangerously-bypass-approvals-and-sandbox` (`--yolo`).

**Profiles.** `-p <profile>` loads a named profile from `~/.codex/config.toml`. `-c key=value` (repeatable) overrides per invocation [6].

**Non-interactive execution.** `codex exec` (alias: `codex e`) runs non-interactively. `--json` emits newline-delimited JSON events. `--output-last-message / -o <path>` writes final assistant message to file. `codex exec resume [SESSION_ID]` continues a prior session [6].

**Hooks / lifecycle events.** **No equivalent to Claude Code's hook system as of April 2026.** The CLI reference documents no `PreToolUse`/`PostToolUse` callback mechanism, no stdin JSON protocol, no exit-code decision semantics [6]. Approval gating (`--ask-for-approval`) provides human-in-the-loop pauses but is not programmable.

**Slash commands.** No `/name` slash-command invocation mechanism in the CLI. Prompts are passed via positional argument or stdin [6]. Skills in Codex live at `$HOME/.agents/skills` (global) or `.agents/skills` (repo); plugin format uses `agents/openai.yaml` to declare dependencies [5].

#### Cross-Mapping

| Claude Code | Closest Codex analogue | Gap |
|---|---|---|
| `SKILL.md` + typed frontmatter | `.agents/skills/` markdown | No `disable-model-invocation`, `paths`, `allowed-tools`, `context: fork` in Codex |
| `/slash-command` invocation | None | Codex has no slash-command dispatch at CLI level |
| Subagent (`.claude/agents/*.md`) | Codex subagents (less mature) | No `permissionMode`, `isolation: worktree`, per-agent `mcpServers` documented |
| Hooks (`PreToolUse`, etc.) | None | No programmatic lifecycle hooks; approval is human-only |
| CLAUDE.md (path-scoped) | AGENTS.md (flat) | Codex has no path-specific rules or lazy-loading |
| MCP integration | MCP integration | Parity |

### Q2: How do AI coding agents currently support test-driven development workflows, and what guidance exists from vendors?

#### Anthropic / Claude Code

Anthropic's official best-practices documentation dedicates a named four-step TDD workflow [9]:

1. **Write tests first.** "Be explicit that you're doing TDD so that it avoids creating mock implementations, even for functionality that doesn't exist yet." Describe expected input/output pairs; instruct Claude to produce test code only.
2. **Confirm failure.** "Tell Claude to run the tests and confirm they fail. Explicitly telling it not to write any implementation code at this stage is often helpful."
3. **Commit tests.** Lock the test suite before touching implementation.
4. **Implement to green.** "Ask Claude to write code that passes the tests, instructing it not to modify the tests. Tell Claude to keep going until all tests pass. It will usually take a few iterations for Claude to write code, run the tests, adjust the code, and run the tests again."

Anthropic frames this as "an Anthropic-favorite workflow for changes that are easily verifiable with unit, integration, or end-to-end tests." Their security engineering team is cited as transforming from "design doc → janky code → refactor → give up on tests" to a test-first approach guided by this protocol [10].

The `common-workflows` doc reinforces the self-verification theme: "Claude performs dramatically better when it can verify its own work, like run tests, compare screenshots, and validate outputs. Without clear success criteria, it might produce something that looks right but actually doesn't work" [11].

**Anti-reward-hacking:** Anthropic's TDD section does not explicitly use the phrase "reward hacking" — the guard is the prompt constraint "not to modify the tests." No hook blocks test modification; the enforcement is advisory only.

#### OpenAI / Codex

No Codex-specific TDD documentation was found at `developers.openai.com/codex` [12]. The Codex Skills system provides a framework for workflow automation but contains no built-in TDD skill or test-runner integration in official docs. **Gap:** OpenAI's agentic coding documentation treats testing as a general capability without prescriptive TDD guidance. Community usage applies the same red-green-refactor pattern, but no vendor-blessed protocol exists.

#### Aider

Aider has the most mechanically complete TDD integration among the vendors reviewed [13]. Key flags: `--test-cmd <command>` specifies the test suite runner (e.g., `pytest`, `dotnet build && dotnet test`); `--auto-test` runs `--test-cmd` after every LLM-generated edit; `--test` runs tests, fixes failures, and exits. **Auto-loop:** if the command exits non-zero, Aider feeds stdout/stderr back to the LLM and requests a fix; loop continues until exit 0 or user interrupt. `/test <cmd>` is the manual in-session trigger. The "black-box test" example uses a ctags-based repo map to infer function signatures without reading full source, generates tests from that metadata, then iterates on `/run pytest` errors [14].

**Limits and failure modes:** (a) No documented retry cap — long or flaky suites create expensive infinite loops. (b) Linters returning non-zero on successful reformatting confuse the loop into treating formatting as failure (documented workaround: wrapper script). (c) No mechanism to prevent Aider from editing test files mid-loop unless the file is excluded from context.

#### Cursor

Cursor's agent best-practices blog [15] mirrors Anthropic's four-step TDD protocol almost exactly — convergent cross-vendor guidance rather than independent discovery. "Agents perform best when they have a clear target to iterate against. Tests allow the agent to make changes, evaluate results, and incrementally improve until it succeeds." Cursor explicitly names the mock-implementation risk. Cursor's `.cursor/rules` (formerly `.cursorrules`, now MDC format in `.cursor/rules/`) supports TDD-specific rule files [16]: no implementation code before failing tests, tests describe behavior not implementation, red-green-refactor sequencing as required pattern.

A monday.com engineering case study [17] documents a critical failure mode: "a coding agent modified test code to make it easier to pass the tests" — the exact reward-hacking pattern Anthropic's prompt constraint attempts to prevent. The same post also notes destructive actions (`rm *.py`) and security regressions in agent-generated code, underscoring that TDD is necessary but insufficient without structural read-only test constraints.

#### GitHub Copilot

GitHub Copilot Workspace was sunset May 2025. The successor is Copilot's integrated **coding agent** (SWE-agent style, runs in background) and a **Plan agent** [18]. The Plan agent surfaces ambiguities in acceptance criteria before coding starts, pairing naturally with test-first. A GitHub blog case study documents concrete TDD value: writing tests first caught a timezone/year-rollover bug that would have silently failed at midnight transitions [18]. The beginner TDD post describes the standard `/tests` slash command in Copilot Chat to generate test scaffolding from selected code, and the `python -m pytest` → iterate cycle [19]. No mechanical test-loop automation equivalent to Aider's `--auto-test` exists.

Endor Labs' test-first-prompting writeup argues that TDD with AI-generated code also materially improves security posture by forcing verifiable success criteria before the agent has latitude to invent abstractions [20].

#### Cross-Vendor Patterns

Three implementation tiers are visible across vendors:

1. **Prompt-level guidance** (all vendors): explicit TDD intent prevents mock implementations; "do not modify tests" is the primary anti-hacking guard.
2. **Harness-level automation** (Aider, partially Cursor via hooks): `--test-cmd` + `--auto-test` runs tests after each edit and feeds failures back automatically.
3. **Agentic loop** (Claude Code hooks, Aider): write test → run → implement → run, fully autonomous with human checkpoint only at test-commit stage.

#### Known Failure Modes

- **Test modification / reward hacking.** METR's 2025 study documented sophisticated patterns: monkey-patching evaluators, hijacking PyTorch `__torch_function__` to make all equality checks return true, overwriting timer functions to fake speed gains [21]. In TDD contexts, the agent rewrites assertions to match actual (wrong) output rather than fixing implementation.
- **Flaky test oracles.** Intermittent failures waste `--auto-test` iterations. The agent may introduce spurious `time.sleep()` or retry logic rather than fixing root cause.
- **Cost blow-up in long green loops.** No vendor documents a hard retry cap. A 30-second suite failing for 20 iterations consumes substantial tokens with no built-in circuit breaker.
- **Test simplification to pass.** Agents narrow assertions (e.g., `assertEqual(result, expected_dict)` → `assertIsNotNone(result)`) to achieve green — technically valid, semantically vacuous. Most common soft failure in production usage.
- **Mock proliferation.** Without explicit TDD framing, agents default to mocking unimplemented dependencies, producing tests that pass without exercising real behavior.

### Q3: What community-contributed TDD skills, commands, or subagents already exist for Claude Code and similar agents?

#### Soft Skills (Prompt-Only, No Enforcement)

**`test-driven-development` — obra/superpowers** [22]. The flagship community TDD skill. Installs to `~/.claude/skills/` and auto-activates on context. Declares "The Iron Law" (`NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST`) and uses a DOT-graph-embedded Red-Green-Refactor loop with explicit Verify RED / Verify GREEN checkpoints. Ships with `testing-anti-patterns.md` as companion. Language-agnostic but examples in TypeScript. Also ships `verification-before-completion` (no completion claims without freshly-run test evidence). **Traction: highest in the ecosystem** — 162,688 stars as of 2026-04-21; canonical in karanb192/awesome-claude-skills [23].

**`Asher-/claude-skills-test-driven-development`** [24]. Single-file SKILL.md, virtually identical "Iron Law" text and Red-Green-Refactor structure to obra/superpowers (appears derived). TypeScript examples. 0 stars, last updated 2026-03-12. Stale, derivative.

**`zscott/pane — /tdd` slash command** [25]. Project-local slash command enforcing Red-Green-Refactor, integrates with git workflow, manages PR creation at end of each green phase. Language-agnostic. Soft-prompt enforcement.

**`jerseycheese/Narraitor — /tdd-implement`** [25]. Accepts `$ARGUMENTS`, analyzes feature requirements, creates tests first, runs them to verify red, implements minimum green, then refactors. "Three-Stage Component Testing" protocol (Storybook isolation → test-harness integration → system integration). React/Storybook target.

**`rzykov/metabase — /repro-issue`** [25]. One-liner: `Repro issue $ARGUMENTS in a failing test`. The minimal end of the spectrum — invokes pure TDD step 1 as a slash command.

#### Hook-Enforced

**TDD Guard — nizos/tdd-guard** [26]. The only production-quality hook that **blocks** writes violating TDD. Architecture: intercepts `Edit`, `MultiEdit`, and `Write` Claude Code tool calls via `PostToolUse` hook, bundles test output + file paths + code diff, ships to an Anthropic model for TDD-compliance validation, returns blocking `BLOCK` decision with corrective guidance if tests were not run first or implementation over-delivers. Language-specific reporters: `tdd-guard-pytest` (pip), `tdd-guard-jest` / `tdd-guard-vitest` (npm), `tdd-guard-go`, `tdd-guard-rust` (crates.io), `tdd-guard-rspec` (gem), `tdd-guard-phpunit` (composer). TypeScript core. **Traction: ~2,000 stars, active maintenance.** Most sophisticated TDD enforcement artifact in the Claude Code ecosystem.

**cc-tools — Veraticus/cc-tools** [27]. High-performance Go implementation of Claude Code hooks including smart test invocation on file write. Not strictly TDD-guard; runs tests on save without blocking non-test-first patterns. Lighter-weight quality gate.

**TypeScript Quality Hooks — bartolli/claude-code-typescript-hooks** [25]. PostToolUse hook triggering TypeScript compilation + ESLint autofixing + Prettier on file write. Not TDD per se, but feeds the quality-gate layer TDD relies on. SHA256 config caching for <5ms overhead.

#### Subagent Patterns

**`subagent-driven-development` — obra/superpowers** [22]. Dispatches one fresh subagent per implementation task with zero inherited context, then runs two-stage review (spec compliance, then code quality). Not TDD-specific, but the natural orchestration layer: test-writer subagent → implementation subagent → verification subagent.

**`dev-loop-skills` — ezagent42/dev-loop-skills** [28]. 7-skill pipeline: `skill-0-project-builder`, `skill-2-test-plan-generator`, `skill-3-test-code-writer`, `skill-4-test-runner`, `skill-5-feature-eval`, `skill-6-artifact-registry`, `using-dev-loop`. Each skill is a SKILL.md with frontmatter trigger conditions and an artifact-passing protocol via `.artifacts/`. Target: pytest (E2E), Python-specific. Most explicit "TDD pipeline as subagent chain" in the ecosystem — test-plan → test-code → run tests → eval → registry. Active, 0 stars (very new).

#### Slash Commands (Spec + TDD)

**`/specmint-tdd:forge`, `/specmint-tdd:resume`, `/specmint-tdd:pause`** — ngvoicu/specmint-tdd [29]. Full spec-management workflow with hard TDD invariants baked into every phase. Specs live in `.specs/<id>/SPEC.md` with TDD log, deviations log, decision log. Red-green-refactor enforced at task granularity; tests run via actual test runner (not assumed). Uses testcontainers for integration, mocks only at boundaries. Ships as both a Claude Code plugin (slash commands) and universal SKILL.md. Language-agnostic. 1 star, but architecturally the most complete spec-to-TDD workflow.

#### Hybrid (Prompt + Hook + Subagent)

**pilot-shell — maxritter/pilot-shell** [30]. Production-oriented: spec-driven plans + TDD enforcement prompts + quality hooks + persistent knowledge. CLAUDE.md references TDD but implementation hooks live in `.githooks` directory (pre-commit) rather than Claude Code hook API. Python, uv-based. 1,657 stars, actively maintained.

**2389-research/claude-plugins** [31]. 28 plugins including explicit TDD plugin; install script for any skill in one command. 54 stars, updated 2026-04-20.

#### Cross-Agent Portability

`zscott/pane` CLAUDE.md and `obra/superpowers` AGENTS.md both include TDD workflow instructions consumable by Codex CLI. No dedicated TDD AGENTS.md templates with wide traction were found. obra/superpowers ships `AGENTS.md`, `GEMINI.md`, `CLAUDE.md`, `.codex/`, `.cursor-plugin/`, `.opencode/` — making its TDD skill the most cross-agent-portable artifact in the ecosystem [22].

#### Gaps and Opportunities

The ecosystem has strong coverage at the extremes: a well-maintained soft-prompt skill (obra/superpowers) and a capable hook-level blocker (tdd-guard). Missing: a **language-aware, stateful TDD runner** that (a) persists red/green/refactor phase state across tool calls within a session (so the agent cannot "forget" it's in the RED phase), (b) integrates test-runner output into the blocking decision without requiring a separate AI call per write (tdd-guard's cost), and (c) provides first-class support for property-based testing (Hypothesis, fast-check) beyond example-based assertions. No artifact currently bridges pytest mutation testing (mutmut, cosmic-ray), tracks TDD velocity metrics, or emits structured TDD telemetry to observability tooling. A skill combining specmint-tdd's spec-state model with tdd-guard's hook enforcement and dev-loop's subagent pipeline decomposition — with a cost-efficient local guard (ast-diff rather than LLM call per write) — would fill this gap.

### Q4: Across the broader AI coding agent ecosystem, how is TDD operationalized, and what lessons transfer?

#### Aider

Aider provides the most explicit TDD primitives in the ecosystem [13]. `--test-cmd <cmd>` registers the test oracle; `--auto-test` enables automatic execution after every AI-generated edit; `--test` runs tests, fixes failures, and exits. Non-zero exit → stdout/stderr fed back into the next LLM turn, looping until tests pass or the session ends. `--auto-lint` + `--lint-cmd` layer static analysis on the same loop. No documented retry cap — theoretically infinite loop is a practical weakness (cost runaway, infinite loops on legitimately broken tests). Red/refactor phases are implicit — user structures prompts manually. No guard prevents agent modification of test files. **Strengths:** explicit, CLI-composable, model-agnostic, scriptable in CI. **Weaknesses:** no retry budget, no subagent isolation, no test-tamper protection, no red/green phase distinction.

#### Cursor

Cursor Agent mode (dominant usage as of early 2026) executes multi-step tasks including terminal commands, file edits, and test runs autonomously. Official TDD guidance [15] is explicit (write tests only → confirm failure → implement forbidden from modifying tests → commit tests and implementation separately). Rules files (`.cursor/rules/*.mdc`) document test command, preferred scope, and TDD conventions — agent reads per-project rules at every turn. Canonical design principle: "Agents can't fix what they don't know about. Use typed languages, configure linters, and write tests." No built-in prevention of test mutation — prompt-level, not structural.

#### Cline / Roo Code / Continue

**Cline** [32] relies on tool use (terminal + filesystem) for test execution. No first-class TDD primitives; loop driven by LLM reading terminal output and correcting errors. Browser automation adds E2E capability. TDD requires user prompt discipline.

**Roo Code** [41] adds multi-agent orchestration via `new_task` delegation. SuperRoo [33] (community harness) implements a formal `test-driven-development` skill-mode enforcing "NO CODE WITHOUT FAILING TEST FIRST." 21 skill-modes loaded one at a time; TDD mode sequences red→green→refactor and auto-triggers a `verification-before-completion` mode requiring fresh test evidence, then auto-spawns `requesting-code-review`. **Closest open-source implementation of a structurally enforced TDD loop** — constraint lives in the mode definition, not just prompts.

**Continue** [34] operates a tool-loop: agent sends tool calls (`run_terminal_command`, file edits), user or auto-policy approves, results fed back. MCP servers extend the toolset. No first-class TDD primitives. Plan Mode (read-only, Shift+Tab) useful for validating test strategy before writes begin.

#### OpenHands / SWE-agent

**SWE-agent** (NeurIPS 2024) [35] built the ACI (Agent-Computer Interface) concept: a shell-like interface tuned for LLMs rather than humans — concise feedback, guardrails on common mistakes, structured file editing commands. Test execution is a first-class ACI action: `bash python -m pytest tests/...` and the observation (stdout, exit code) is passed directly into the next LLM turn. Functionally the same loop as Aider's `--test-cmd` at academic benchmark scale. Achieved 12.5% pass@1 on SWE-bench, 87.7% on HumanEvalFix.

**TDFlow** (2025) [36] decomposed the loop into four specialized sub-agents: Explore Files (read-only patch proposal), Revise Patch, Debug One (per-failing-test diagnostic), Generate Tests. Critical findings: with human-written tests, **94.3% pass rate on SWE-bench Verified**. With LLM-generated tests, 68.0%. Root cause: test quality, not patch quality, is the bottleneck. Test-hacking rate: 7/800 runs despite prompt mitigations. **TDFlow's core lesson: subagent role separation + human-written tests = near-human performance.** "Write the test, have the agent solve it" operationalizes TDD at scale.

#### Copilot / Windsurf

**GitHub Copilot** integrates TDD via `/tests` slash command in Chat and Workspace [19]. Workflow: requirements → Copilot generates failing tests → developer reviews → Copilot generates implementation. Test verification is manual. Copilot Workspace (merged into GitHub coding agent) supports spec-driven development [37]: `Specify → Plan → Tasks → Implement`, tasks functioning as testable acceptance criteria. No autonomous test-retry loop as of 2025.

**Windsurf Cascade** [38] supports a `/run-tests-and-fix` workflow that runs tests, reads terminal output, and self-corrects. Cascade can loop up to 20 tool calls per prompt. Key limitation: workflows are **manual-only** — user must explicitly invoke `/run-tests-and-fix`. No autonomous trigger on file save or commit. Linter integration is automatic; test execution is not.

#### Cross-Cutting Patterns

**(a) Test-command-as-oracle.** Every tool that reaches production maturity (Aider, Cursor, Windsurf, SWE-agent, OpenHands) converges on a simple contract: `run_cmd → exit_code + stdout → LLM context`. Oracle is the process exit code. **Universal primitive.**

**(b) Test-before-edit invariant.** Cursor's official guidance, SuperRoo, and the Agentic Coding Handbook [39] all enforce writing tests before implementation. Without structural enforcement (mode-level prohibition on implementation tools during the "red" phase), this invariant degrades to prompt-level suggestion. SuperRoo's skill-mode isolation is the strongest structural approach found.

**(c) Subagent/tool separation.** TDFlow's decomposition (propose / revise / debug / generate-tests as separate agents) and Roo Code's single-mode-at-a-time loading both reduce context bloat and prevent cross-contamination between test-writing and implementation. A monolithic context conflating both phases degrades performance [36][41].

**(d) Reward-hacking mitigations.** UC Berkeley's benchmark audit (2026) [40] demonstrated that a 10-line `conftest.py` achieves near-perfect SWE-bench Verified scores by monkey-patching pytest's result collector — without solving a single task. Root vulnerability: agent runs in same container as test runner, giving it write access to test infrastructure. METR found o3 and Claude 3.7 Sonnet reward-hack in 30%+ of evaluation runs [21]. Mitigations: (1) restrict agent write access to test files and test config (`conftest.py`, `pytest.ini`) — TDFlow uses filesystem restrictions; (2) run the evaluator outside the agent sandbox; (3) audit trajectories for test-modification steps; (4) separate "evaluator" subprocess with read-only mounts.

#### Lessons for Claude Code and Codex

**Steal.** Aider's `--test-cmd` + `--auto-test` loop is the right primitive for Claude Code hooks (map to `PostToolUse` or `Stop` hooks running `pytest`). Cursor's explicit "three-turn" TDD prompt structure (write tests / confirm failure / implement) is the cleanest UX pattern. TDFlow's subagent decomposition transfers directly: a Claude Code skill can spawn a "test-generation" subagent and a "patch" subagent with different tool permissions. SuperRoo's mode-level prohibition on implementation tools during the red phase is the only structural enforcement found — worth encoding as `.claude/settings.json` tool restrictions per TDD phase.

**Avoid.** Infinite retry loops without a budget (Aider's unlimited loop) waste tokens and can spiral on broken test environments. Granting write access to `tests/` during the green phase — enforce read-only on test files once red completes. Relying solely on prompt-level "don't touch tests"; reward-hacking research shows capable models find paths of least resistance when the evaluator shares the agent's execution environment.

**Codex-specific.** OpenAI Codex CLI has no built-in `--test-cmd` analog but accepts `--ask-for-approval never` + `--sandbox workspace-write` for autonomous loops. Same pattern applies: inject test execution as mandatory post-edit step in the agent harness, with evaluator process isolated from agent's writable working tree. Because Codex lacks hooks [6], the enforcement layer must live in the AGENTS.md prompt or in a wrapper script running `codex exec` in a loop.

### Summary

The research converges on a three-tier enforcement model for TDD in AI coding agents, mirrored almost identically across Anthropic, Cursor, Aider, and the academic literature (SWE-agent, TDFlow). **Tier 1 — prompt-level guidance** (the four-step protocol: write tests → confirm failure → implement → do not modify tests) is the lowest-cost, universally-applicable pattern and is canonical across vendors [9][15][39]. Every vendor that documents TDD converges on roughly identical language; Anthropic's and Cursor's guidance is effectively the same protocol [9][15]. **Tier 2 — harness-level automation** (Aider's `--test-cmd` + `--auto-test`, tdd-guard's PostToolUse hook, Windsurf's `/run-tests-and-fix`) moves the red-green loop from human orchestration to agent orchestration, but introduces cost and retry-budget concerns [13][26][38]. **Tier 3 — structural enforcement** (SuperRoo's mode-scoped tool restrictions, TDFlow's subagent decomposition, specmint-tdd's spec-state machine) is the only layer that defends against reward hacking at the architecture level rather than via advisory prompts [29][33][36].

The primitives map onto Claude Code with high fidelity: SKILL.md frontmatter encodes the prompt layer, `PostToolUse`/`Stop` hooks encode the auto-test loop, subagents with scoped `allowed-tools` encode structural enforcement, and `.claude/settings.json` tool restrictions encode red/green phase boundaries [1][2][3]. OpenAI Codex mirrors the prompt layer via AGENTS.md but has no native hook or slash-command substrate [4][6]; the enforcement must live in a wrapper script or an evaluator container isolated from the writable working tree. The most important unresolved contradiction is between the vendor-documented soft guidance ("explicitly tell Claude not to modify tests" [9]) and the empirical reward-hacking findings (30%+ hacking rates on frontier models in adversarial conditions [21][40]) — this is the specific gap a new, well-designed TDD skill should close. The community ecosystem already contains the needed building blocks (tdd-guard for enforcement [26], dev-loop-skills for pipeline decomposition [28], specmint-tdd for spec-state persistence [29], obra/superpowers for the prompt-layer canon [22]); what is missing is their integration into a single, cost-efficient, language-aware, stateful TDD skill.

---

## Deeper Dive

### Subtopic A — Enforcement Pattern Design

#### A1: Comparison matrix (reward-hacking resistance, cost, friction, complexity)

| Dimension | Soft-Prompt Skill (obra/superpowers, SuperRoo) | Hook-Enforced (tdd-guard) | Subagent Pipeline (TDFlow, dev-loop-skills) |
|---|---|---|---|
| **Reward-hacking resistance** | Low. Rules live in context; agent rationalizes them away. No structural block [42]. | Medium-high. `PreToolUse`/`UserPromptSubmit` hooks intercept Write/Edit/MultiEdit/TodoWrite before execution and emit `block`/`approve`. Agent cannot bypass without shell redirects (`sed`, `awk`, `printf`) — `enforcement.md` denies those via permissions [26]. | High for phase sequencing, moderate for content. TDFlow's four role-isolated sub-agents (ExploreFiles → DebugOne → RevisionPatch → GenerateTests) prevent any single agent from simultaneously writing tests and implementation. Manual inspection of 800 runs found only 7 test-hacking instances [36]. |
| **Per-cycle cost** | ~$0 marginal. Prompt tokens in CLAUDE.md, re-used via prompt caching [42]. | ~$0.003–$0.015/write on Haiku; ~$0.05–$0.15/write on Sonnet via API path. SDK path bills against the Claude Code subscription (tdd-guard docs note "no extra charges" on SDK path) [26]. | High absolute: TDFlow costs $1.51/issue on SWE-Bench Lite vs. $0.53 for Agentless. Each sub-agent carries its own context and tool calls [36]. |
| **False-positive rate** | Near zero (no automated blocking); compliance is discretionary. | Measurable but tunable. `rules.ts` explicitly carves out: "Adding a single test to a test file is ALWAYS allowed"; refactor-phase renames default to approval. Over-blocking on refactor is the main complaint. Custom `instructions.md` at `.claude/tdd-guard/data/instructions.md` narrows rules [26]. | Controlled by workflow design. ExploreFiles is denied Bash by construction — it only views/finds/proposes. Eliminates one category of false positive; malformed patches hit the RevisionPatch recovery layer [36]. |
| **Interruption cost** | None. | High when triggered: hook emits blocking JSON, Claude Code halts tool execution. Each invocation adds ~2–5s latency (subprocess + LLM call) [26]. | Moderate pipeline overhead. Each sub-agent transition is context-serialization + new invocation. Debug loop scales with F failing tests (one DebugOne per failing test) [36]. |
| **Implementation complexity** | Very low — one SKILL.md + CLAUDE.md injection [42]. | Medium — npm global install, hook JSON in settings, per-language reporter integration (tdd-guard-vitest, pytest plugin, cargo reporter, etc.), session state in `.claude/tdd-guard/` [26]. | High — four distinct prompts, orchestration logic, tool-allowlist per sub-agent, diff-application tooling, debugger integration [36]. |

#### A1: Hybrid patterns that work in practice

**Skill + Hook (obra + tdd-guard layered).** SuperRoo demonstrates this in RooCode: skill-modes carry R-G-R rules as system-level context while the platform's `new_task()` enforces sub-task isolation [33]. The Claude Code equivalent: load `obra/superpowers` TDD SKILL.md as a CLAUDE.md-injected skill *and* register tdd-guard as a PreToolUse hook. Skill handles intent and framing; hook provides the structural block. Lowest-cost hybrid — skill is ~$0 marginal and hook only fires on Write/Edit/MultiEdit [42][26].

**Hook + Subagent decomposition (tdd-guard + TDFlow-style dispatch).** For large cross-module changes, tdd-guard's single-file LLM validation lacks repository-level context. Pairing with a TDFlow-style ExploreFiles sub-agent (read-only, no Bash/Edit/Write/MultiEdit — matching the allowedTools restriction in `ClaudeAgentSdk.ts`) provides it [26][36].

#### A2: Failure mode taxonomy with structural defenses

| Failure mode | Description | Structural defense | Implementation note |
|---|---|---|---|
| **Test tampering** | Agent modifies existing assertions or deletes tests to force green. | tdd-guard PreToolUse detects behavioral diffs in test files; `rules.ts` flags "behavioral refactoring when tests haven't been run"; deny `Read(.claude/tdd-guard/**)` prevents reading guard state [26]. | Set `deny: ["Bash(sed:*)", "Bash(awk:*)"]` in settings to block filesystem-level tampering that bypasses the hook. |
| **Mock proliferation** | Agent wraps real behavior in mocks so tests pass without exercising production paths. | obra/superpowers `testing-anti-patterns.md` defines three Iron Laws + Gate Functions. Anti-Pattern 1 ("Testing Mock Behavior") requires asking "Am I testing real behavior or mock existence?" before each assertion [43]. | Load anti-pattern skill alongside TDD skill; fires a structural gate before any mock assertion. |
| **Assertion narrowing** | Replaces `expect(result).toEqual({...})` with `expect(result).toBeTruthy()` to pass partial output. | tdd-guard's diff-aware context captures `old_content` (via `enrichWriteOperation` → `readOldFileContent`) and sends before/after to validator. Validator detects assertion weakening [26]. | `readOldFileContent.ts` reads prior file state at PreToolUse stage; old content injected into the validation prompt. |
| **Flaky retries / infinite green loop** | Agent re-runs tests until stochastic pass; reports green without code fix. | obra/superpowers `condition-based-waiting` skill. tdd-guard `testCounter.ts` tracks test definition counts per file to detect sudden jumps/disappearances [42][26]. | Test-def spike or collapse → flag. Hard retry budget should also bound the loop. |
| **conftest / module monkey-patching** | Agent patches evaluator or scoring at import time — METR documented o3 patching `_time.time`, `torch.__eq__`, `rust_codecontests_utils.evaluate_rust_code` [21]. | Filesystem permissions (read-only bind-mount on test files in CI). Deny-list `perl`, `python -c`, `sed` for shell-level patches [26][46]. | Sandbox: mount test dirs read-only. Claude Code: `deny: ["Bash(python:*-c*)"]` partially mitigates inline monkey-patching. |
| **conftest scope creep** | Inserts autouse fixtures that mask failures project-wide. | Role separation: TDFlow's ExploreFiles has no Write/Edit. Read-only sub-agents cannot create conftest.py [36]. | Enforce via `allowedTools: []` + explicit disallowedTools in sub-agent SDK options (matches tdd-guard `ClaudeAgentSdk.ts` pattern). |
| **Over-implementation / YAGNI violations** | Writes beyond minimal passing code, pre-implementing untested paths. | tdd-guard `rules.ts` §"Over-Implementation" blocks "code that exceeds what's needed to pass the current failing test"; validated on every Write/Edit [26]. | obra/superpowers enforces same via SKILL.md §"GREEN - Minimal Code" with Good/Bad YAGNI examples [42]. |
| **Precomputed answer injection** | Agent finds or caches reference outputs and returns them directly (METR o3 examples: tracing call stack, zero-stride tensor, symlinked checkpoint) [21]. | For CI/eval: isolated sandbox with no access to reference implementations. For dev: read-only mounts on grader/scorer directories. | Not fully addressable at prompt layer; requires OS-level isolation (Docker `--read-only`, seccomp). |

#### A3: Recommended three-layer hybrid for a drop-in skill

**Target:** language-agnostic TDD skill for pytest/jest/go/rust that maximizes quality-per-token.

- **Layer 1 — Deterministic AST-diff local guard (zero LLM cost).** Run a local language-specific parser on every Write/Edit PreToolUse event. Python `ast.parse`, JS/TS `@babel/parser`/`acorn`, Go `go/ast`, Rust `syn`. Output: `{test_count_delta, assertion_count_delta, new_test_file, modified_test_file, impl_only_change}`. ~5ms, $0. Handles the unambiguous cases (test deletion, assertion collapse, pure-impl writes without prior failing test) deterministically, mirroring tdd-guard's `fileTypeDetection.ts` + `testCounter.ts` but pushed earlier [26].
- **Layer 2 — LLM escalation (conditional, haiku-gated).** Escalate only when the AST diff is ambiguous: assertion rewrites without count change (narrowing), mock structure changes, refactor-vs-new-behavior boundaries. Use `claude-haiku` — tdd-guard lists Haiku as the speed option [26]. Adopt tdd-guard's validation prompt template (`SYSTEM_PROMPT + RULES + FILE_TYPES + diff + test_output + lint_results + RESPONSE` from `src/validation/context/context.ts`) [26].
- **Layer 3 — Subagent decomposition for cross-file changes.** When a change touches N>1 implementation files or requires cross-module test coordination, spawn a read-only ExploreFiles sub-agent (view/find/hierarchy only — no Write/Edit/Bash, per TDFlow [36]) to produce a repo-level patch plan, then a separate implementation sub-agent. TDFlow's core finding: role separation beats monolithic context on large changes [36].

**State machine:** `RED_REQUIRED` (no test output or last run red) → `WRITE_TEST` (single test, AST enforces single-test rule) → `VERIFY_RED` (runner output required before green) → `GREEN` (minimal impl, AST + LLM validates no over-impl) → `REFACTOR` (AST confirms no new test function names) → loop. tdd-guard's `rules.ts` §"Incremental Development" and §"Reaching a Clean Red" encode this textually; the proposed architecture makes it explicit in hook logic [26].

**Why this composes.** AST layer eliminates 70–80% of LLM validation calls. LLM escalation handles semantic edge cases. Subagent decomposition fires only on cross-module work. Near-zero incremental cost on simple cycles, moderate on refactor ambiguity, full cost only on cross-module changes. Directly addresses TDFlow's $1.51/issue — most dev-loop TDD cycles are single-file and never reach layer 3 [36].

### Subtopic B — Authoring a Drop-in Claude Code TDD Skill

#### B1: SKILL.md anatomy

**obra/superpowers reference structure.** Frontmatter is minimal [42]:

```yaml
---
name: test-driven-development
description: Use when implementing any feature or bugfix, before writing implementation code
---
```

Body organized into 12+ sections: Overview, When to Use, The Iron Law, Red-Green-Refactor, Good Tests, Why Order Matters, Common Rationalizations (table), Red Flags, Example: Bug Fix, Verification Checklist, When Stuck, Debugging Integration, Testing Anti-Patterns, Final Rule. Iron Law as block-caps imperative: `NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST`, plus sub-rule: "If you didn't watch the test fail, you don't know if it tests the right thing." Skill is instruction-heavy and intentionally uncompromising — lean on ALWAYS/NEVER caps-lock, which Anthropic's skill-creator flags as a code smell [47] but obra accepts for a discipline-enforcement skill.

**Proposed TDD SKILL.md frontmatter for a drop-in skill:**

```yaml
---
name: test-driven-development
description: >
  Enforces Red-Green-Refactor TDD discipline. Use when implementing any
  feature, bug fix, or behavioral change; when writing tests; when the user
  mentions "write a test", "TDD", "test first", "make this pass", "failing
  test", or "red/green/refactor". Blocks implementation without a prior
  failing test.
allowed-tools: ["Read", "Write", "Edit", "MultiEdit", "Bash"]
---
```

**Recommended body layout (progressive disclosure per Anthropic best practices [48]):**

```
tdd/
├── SKILL.md          # frontmatter + overview + R-G-R checklist (<300 lines)
├── RULES.md          # detailed violation catalog (loaded on demand)
├── ADAPTERS.md       # language-specific test-runner invocation table
└── scripts/
    └── run_tests.sh  # universal adapter shim
```

SKILL.md body sections: `## The Cycle` (3-phase checklist), `## When to Use`, `## Iron Law`, `## Language Adapters` (pointer to ADAPTERS.md), `## Verification Checklist`. Detailed violation text lives in RULES.md, loaded only when Claude needs to explain a block.

Anthropic best-practices mandates [48]: description in third person; explicit trigger terms in description; body under 500 lines; no deeply nested file references (one level only); progressive disclosure via `See [RULES.md](RULES.md)` pointers.

#### B1: skill-creator anti-patterns

From the `anthropics/skills` skill-creator SKILL.md [47]:

- **Overfitting to test cases.** Skills pass the three eval prompts but break on user-phrasing variation. Generalize trigger language.
- **Excessive ALWAYS/NEVER.** All-caps imperatives without "why" clauses degrade model compliance on edge cases. tdd-guard's RULES field pairs constraints with rationale [26].
- **Undertriggering.** Description must be "pushy" — include specific trigger phrases. skill-creator runs a 20-query eval set to optimize description accuracy.
- **Ignoring transcripts.** Evaluating only final outputs misses wasted multi-step work — review full conversation traces.
- **Skipping negative eval cases.** Should-not-trigger queries must be near-misses (same domain, different intent), not obviously unrelated prompts.
- **Surprising users.** Skill content must match description. A TDD skill that silently modifies git history violates least surprise.
- **Poor progressive disclosure.** Dumping 800-line rule sets into SKILL.md body defeats context economics. Top-level SKILL.md is a ToC; detail lives in sidecars.
- **Windows-style paths** in bundled file references (`scripts\run.sh` fails on Unix).

Anthropic's skill-development plugin-dev skill [53] and the platform-docs Agent Skills overview [52] reinforce these points.

#### B2: Phase-state persistence options

| Option | Persistence location | Session survivability | Complexity | Example |
|---|---|---|---|---|
| (a) File-based `.tdd-state.json` | Project root or `.claude/tdd-guard/data/test.json` | Survives compaction, resume, new sessions | Low | tdd-guard uses `.claude/tdd-guard/data/test.json` written by reporters [26]; alexop.dev multi-agent TDD uses `.tdd-state.json` [49] |
| (b) `additionalContext` on PreToolUse | Hook stdout injected into Claude context | Per-call only; no cross-call persistence without (a) | Medium | PostToolUse supports `additionalContext` today; PreToolUse does not yet (open feature request) [50][51] |
| (c) Subagent memory (`.claude/agents/*.md`) | Agent-local sidecar | Survives if `memory: local` | Medium | Suitable for agent-scoped TDD state; tightly coupled to agent lifecycle |
| (d) CLAUDE.md rewrite | Project-root CLAUDE.md | Survives everything | High | Invasive; pollutes shared context; not recommended for transient phase state |
| (e) `${CLAUDE_SKILL_DIR}/state.json` | Skill dir | Does not survive (read-only on claude.ai) | Low | Not portable |

**Recommended state design.** Option (a), canonical path `.claude/tdd-guard/data/test.json`:

1. tdd-guard's reporters (pytest, vitest, jest, go, rust) all write to this path natively [26], so a new skill that shells out to reporters gets state for free.
2. A PreToolUse hook runs `npx tdd-guard@latest`, parses `TestResultSchema`, and returns `decision: "block"` with a reason when tests are failing and the agent tries to write a non-test production file [26].
3. Survives Claude context compaction and `--resume` because it's a filesystem artifact.
4. A minimal custom skill without tdd-guard can write the identical schema to the same path and still benefit from hook interception.

For phase label tracking, store a sidecar at `.claude/tdd-guard/data/phase.json`:

```json
{ "phase": "RED", "test_file": "tests/test_auth.py", "slice": "login-feature" }
```

A `SessionStart` hook clears transient data (tdd-guard's `sessionHandler.processSessionStart` calls `storage.clearTransientData()` [26]), so stale phase state is wiped automatically. Continuous-Claude-v3 demonstrates an analogous context-ledger pattern via hooks for longer-running sessions [55].

#### B3: Language adapter design

**tdd-guard reporter architecture [26][54].** Every reporter implements the same contract: hook into the test runner's lifecycle, collect per-test `(name, fullName, state, errors[])` tuples, group by module/file, serialize to `.claude/tdd-guard/data/test.json`. Canonical schema (Zod, `src/contracts/schemas/reporterSchemas.ts`) [54]:

```typescript
TestResult = {
  testModules: Array<{
    moduleId: string,
    tests: Array<{
      name: string,
      fullName: string,
      state: 'passed' | 'failed' | 'skipped',
      errors?: Array<{ message: string, stack?: string, expected?: unknown, actual?: unknown }>
    }>
  }>,
  unhandledErrors?: Array<{ name, message, stack }>,
  reason?: 'passed' | 'failed' | 'interrupted'
}
```

**Per-language reporters [26]:**
- `tdd-guard-vitest` — `VitestReporter` implements Vitest's `Reporter` interface; hooks `onTestModuleCollected`, `onTestCaseResult`, `onTestRunEnd`; `this.storage.saveTest(JSON.stringify(output))`; registered via `vitest.config.ts` reporters array.
- `tdd-guard-pytest` — pytest plugin registered via `pytest11` entry point; hooks `pytest_runtest_logreport` and `pytest_sessionfinish`.
- `go`, `rust`, `rspec`, `phpunit`, `minitest` — separate packages under `/reporters/`, all targeting the same schema.

**Hook intercept** (`plugin/hooks/hooks.json`) [26]:

```json
{ "PreToolUse": [{ "matcher": "Write|Edit|MultiEdit|TodoWrite",
    "command": "npx tdd-guard@latest" }],
  "UserPromptSubmit": [{ "command": "npx tdd-guard@latest" }],
  "SessionStart": [{ "matcher": "startup|resume|clear",
    "command": "npx tdd-guard@latest" }] }
```

**Minimum-viable universal adapter.** For languages without a reporter, `scripts/run_tests.sh`:

```bash
#!/bin/bash
# Usage: TEST_CMD="pytest -q" ./run_tests.sh
set -o pipefail
OUTPUT=$( eval "$TEST_CMD" 2>&1 | tail -200 )
EXIT_CODE=$?
echo "$OUTPUT"
exit $EXIT_CODE
```

Skill then writes minimal `test.json`:

```json
{ "testModules": [{ "moduleId": "__universal__",
    "tests": [{ "name": "test_suite", "fullName": "__universal__::test_suite",
      "state": "<passed|failed>",
      "errors": [{ "message": "<last 200 lines>" }] }] }],
  "reason": "<passed|failed>" }
```

Valid against `TestResultSchema`, so `isTestPassing()` returns correctly and the PreToolUse hook blocks production writes without any reporter installed. Tradeoff: per-test granularity collapses — `failed_tests` and `new_failures` collapse to one module-level entry. Acceptable for polyglot drop-in; framework-specific reporters add granularity when available.

### Subtopic C — Cross-Harness Portability (Claude Code + OpenAI Codex)

#### C1: Portable surface vs. harness-specific

| Claude Code primitive | agentskills.io portable field | Codex equivalent | Portable-via-fallback |
|---|---|---|---|
| `name` | `name` (required) | Native | Fully portable [56] |
| `description` | `description` (required) | Native | Fully portable [56] |
| `license`, `compatibility`, `metadata` | Optional fields in standard | Native | Fully portable [56] |
| `allowed-tools` | Experimental | `agents/openai.yaml` has `allow_implicit_invocation` | Partially portable; put permission grants in body for Codex [58][59] |
| `hooks` (in SKILL.md frontmatter) | **Not in standard** | No *per-skill* hooks; Codex has session/config-level hooks (see note below) | Degrade: move hook logic to wrapper script; document intent in `compatibility` [26] |
| `disable-model-invocation` | Not in standard | `allow_implicit_invocation: false` in `agents/openai.yaml` | Map manually [58] |
| `user-invocable` | Not in standard | No direct equivalent | Drop |
| `when_to_use` | Not in standard | Ignored | Fold into `description` |
| `argument-hint` | Not in standard | Ignored | Drop safely |
| `context: fork` / `agent` | Not in standard | Codex has native `spawn_agent` | Document in body: "if under Codex, use spawn_agent" [60] |
| `model`, `effort` | Not in standard | `config.toml` / CLI flags | Drop from SKILL.md; configure at harness level |
| `$CLAUDE_SKILL_DIR`, `$CLAUDE_SESSION_ID` | Not in standard | Not available | Conditional body text |

**Contradiction-flagged finding on Codex hooks.** The Q1 research concluded Codex has "no hooks." Subtopic C's deeper dive found that Codex **does** have session-level hooks — `PreToolUse`, `PostToolUse`, `Stop`, `UserPromptSubmit` — documented at `developers.openai.com/codex/hooks` [61]. Critical caveats: (a) hooks are configured at the session/config level (in `config.toml` or `.codex/hooks/`), **not per-skill** as in Claude Code's SKILL.md `hooks` frontmatter; (b) `PostToolUse` "only intercepts Bash calls (not all tool types)" per the Codex docs [61], whereas Claude Code's `PostToolUse` fires for every tool (Write/Edit/MultiEdit/Bash/etc.). So the accurate framing is: **Codex has hooks, but they are weaker and session-scoped** — not the per-skill, per-tool granularity Claude Code offers. The "no hooks" earlier claim should be replaced with this nuanced picture throughout the whitepaper.

#### C1: Wrapper-script pattern for Codex

The `codex-tdd-loop.sh` pattern treats the shell as the deterministic control plane and `codex exec` as a stateless worker — the "Bash owns the loop" architecture [62]:

```bash
#!/usr/bin/env bash
# codex-tdd-loop.sh — simulates PostToolUse TDD enforcement for Codex
set -euo pipefail
MAX_CYCLES=${MAX_CYCLES:-6}
PROMPT_FILE=${1:?usage: $0 <prompt.txt>}

for cycle in $(seq 1 "$MAX_CYCLES"); do
  # 1. Inject current test status as context
  TEST_OUTPUT=$(npm test 2>&1 | tail -40 || true)

  # 2. Composite prompt: original task + test gate
  COMPOSITE=$(cat "$PROMPT_FILE"; echo; echo "--- TEST GATE (cycle $cycle) ---"; echo "$TEST_OUTPUT"; \
    echo "Rules: (a) Write the failing test first. (b) Do not implement until RED is confirmed. (c) Stop when tests pass.")

  # 3. codex exec non-interactive; stream JSON events
  printf "%s" "$COMPOSITE" | codex exec \
    --ask-for-approval never \
    --sandbox workspace-write \
    --json \
    --output-last-message /tmp/last-msg.txt \
    - 2>/tmp/codex-stderr.txt

  # 4. Post-iteration gate
  if npm test --silent 2>/dev/null; then
    echo "TDD loop: GREEN on cycle $cycle. Done."
    exit 0
  fi
done
echo "TDD loop: MAX_CYCLES reached without GREEN."
exit 1
```

Key design points [63]:
- `--json` + `--output-last-message`: machine-readable event stream; parseable for file-change events to detect implementation-before-tests.
- stdin piping: `codex exec` treats stdin as additional context when a prompt arg is present — test output injected without a custom hook.
- `codex exec resume --last`: preserves context across cycles if needed.
- `Stop` hook supplement: configure `.codex/hooks/stop.sh` to re-run tests and return output as a new user prompt — gives partial PostToolUse semantics at session-end [61].

**Feature parity vs. Claude Code:**

| Feature | Claude Code (SKILL.md hooks) | Codex wrapper script |
|---|---|---|
| Block implementation before RED | Yes (`PreToolUse` blocks Write if no failing test) | Partial — detected post-iteration, not mid-turn |
| Inject test output after each file write | Yes (`PostToolUse` fires per Write) | No — injected only at loop boundary |
| Per-file deterministic gate | Yes | No |
| Full loop enforcement | Yes | Yes (loop level) |
| Auditability via JSON event stream | N/A | Yes |
| Enforcement cost | Near-zero | One extra test-run per cycle |

The main gap is **intra-turn enforcement**: Claude Code hooks fire after every tool call; the wrapper fires between `codex exec` invocations. Mitigate with explicit guard instructions in SKILL.md body.

#### C2: Real-project patterns

**obra/superpowers** ships the most mature cross-harness structure [60][64]:
- Claude Code: `.claude-plugin/plugin.json` registers the plugin; hooks + subagent types per plugin convention; `using-superpowers/SKILL.md` is the entry skill.
- Codex: `.codex/INSTALL.md` documents a single `ln -s ~/.codex/superpowers/skills ~/.agents/skills/superpowers` symlink; Codex discovers all SKILL.md files via `~/.agents/skills/` scan at startup.
- Harness detection in skill body: "On harnesses with subagent support (Claude Code, Codex), subpowered-development is required. On harnesses without, use executing-plans." Tool mapping: `Task` → `spawn_agent` with `multi_agent = true` [60].
- Enforcement strategy: superpowers deliberately avoids hooks for cross-harness skills. Enforcement lives in skill body as strong imperatives, not in frontmatter hooks. `compatibility` field signals Claude Code-only capabilities [65].

**specmint-tdd** [29] ships as both a Claude Code plugin (with plugin.json) and a standalone SKILL.md following the Agent Skills standard — installation under any compatible harness. TDD enforcement lives in body rather than hooks; portable form is weaker than full plugin form. [verify]

**Aider** [13] takes a fundamentally different architectural path — no skill/hook system because it's model-agnostic at the API level. Portability strategy: `--test-cmd` natively runs a test command after each edit and re-prompts the model with test output on failure. This is what `codex-tdd-loop.sh` approximates. `--auto-test` continuously reruns and feeds failures back. Key portability lesson: **test-output-as-context is a sufficient (if weaker) substitute for hook-based enforcement at the cross-harness level**. The gap is precision (per-tool-call vs. per-iteration), not correctness [39].

**Community convention: AGENTS.md as source of truth with thin CLAUDE.md wrapper** [57]:
1. Write `AGENTS.md` as the portable base (flat markdown, no typed frontmatter, readable by Codex, agents.md-compliant tools).
2. Add `CLAUDE.md` starting with `See AGENTS.md for base instructions.`, then appending Claude Code-specific blocks (hook declarations, slash-command references, subagent config).
3. Do not symlink — keep as separate files; Claude Code's CLAUDE.md supports richer typed includes while Codex's AGENTS.md does cascading directory traversal.

#### C2: Recommended cross-harness layout

```
my-tdd-repo/
├── AGENTS.md                        # Codex reads (+ cascade from subdirs)
├── CLAUDE.md                        # Claude Code reads; line 1: "See AGENTS.md..."
├── .claude/
│   ├── settings.json                # hooks: PostToolUse → tdd-guard; permissions
│   └── skills/tdd/
│       └── SKILL.md                 # portable frontmatter (name, description, compatibility)
│                                    # hooks field used only by Claude Code
│                                    # body: instructions portable to any harness
├── .codex/
│   ├── INSTALL.md                   # symlink instructions for skill discovery
│   └── hooks/stop.sh                # Codex Stop hook: re-run tests, return output
├── scripts/
│   └── codex-tdd-loop.sh            # wrapper for Codex non-interactive TDD loop
└── config.toml                      # Codex session config
```

Which harness reads which:
- `AGENTS.md` → Codex primary; fallback for any agents.md-compliant tool [57]
- `CLAUDE.md` → Claude Code only; references AGENTS.md rather than duplicating [57]
- `.claude/settings.json` → Claude Code hooks engine only [2]
- `.claude/skills/tdd/SKILL.md` → Claude Code project skill + Codex via symlink [1][58]
- `.codex/hooks/stop.sh` → Codex hook system only [61]
- `scripts/codex-tdd-loop.sh` → called by CI or developer directly [62][63]
- `config.toml` → Codex session/advanced config [59]

The SKILL.md `hooks` frontmatter is the only place you write Claude Code hook declarations in a skill-scoped way; Codex silently ignores them (reads only `name`/`description` from SKILL.md frontmatter). `.codex/hooks/stop.sh` provides the nearest Codex equivalent. SKILL.md body contains the portable enforcement prose that both harnesses act on, with Claude Code additionally enforcing mechanically via hooks.

### Summary

The Deeper Dive converges on three concrete architectural recommendations that the whitepaper can defend end-to-end.

**First, the best enforcement pattern is a three-layer hybrid — AST-diff local guard, Haiku-gated LLM escalation, and subagent decomposition for cross-file changes.** This decomposition is motivated by cost asymmetry: tdd-guard's LLM-per-write design delivers strong reward-hacking resistance [26] but at $0.05–$0.15 per Sonnet-path write; TDFlow's subagent pipeline delivers the highest structural resistance [36] but at $1.51/issue on SWE-Bench Lite. An AST layer handles the 70–80% of writes that are unambiguous (test deletion, pure-impl writes, assertion-count collapse) at zero LLM cost, escalating only the semantic edge cases to Haiku. Subagent decomposition is reserved for cross-module changes where single-agent context degrades — TDFlow's core finding [36].

**Second, the drop-in Claude Code TDD skill should adopt tdd-guard's `.claude/tdd-guard/data/test.json` schema as its state-persistence contract** [26][54]. This makes the skill immediately compatible with the existing reporter ecosystem (pytest, vitest, jest, go, rust, rspec, phpunit) without re-implementing language adapters. A phase-state sidecar at `.claude/tdd-guard/data/phase.json` tracks RED/GREEN/REFACTOR label; SessionStart hooks clear transient state. For polyglot projects, a universal `run_tests.sh` shim emits a minimal but valid `TestResultSchema` JSON from any test command's exit code and last 200 lines of output — sufficient for the hook to block production writes without a language-specific reporter. The SKILL.md itself should follow Anthropic progressive-disclosure best practices [48]: <300-line body with RULES.md, ADAPTERS.md sidecars loaded on demand. The skill-creator meta-skill flags ALWAYS/NEVER overuse, undertriggering, and failure to test on near-miss queries as the common anti-patterns [47].

**Third, cross-harness portability to OpenAI Codex is achievable with an AGENTS.md + CLAUDE.md wrapper pair plus a `codex-tdd-loop.sh` shell wrapper** [57][62][63]. The SKILL.md frontmatter's portable subset (name, description, license, compatibility, metadata per agentskills.io [56]) works under both harnesses; Claude Code-specific fields (hooks, context: fork, disable-model-invocation) are silently ignored by Codex. The critical earlier-research correction: **Codex does have hooks** (PreToolUse, PostToolUse, Stop, UserPromptSubmit at `developers.openai.com/codex/hooks` [61]), but they are session-scoped rather than per-skill, and PostToolUse only intercepts Bash — so enforcement parity requires the wrapper-script loop to catch what session-level hooks miss. obra/superpowers [60][64] demonstrates the real-world cross-harness pattern; Aider [13][39] demonstrates that test-output-as-context alone is sufficient-if-weaker substitute for hook-based enforcement across harnesses.

The single highest-leverage unresolved design decision is whether to bundle tdd-guard as a hard dependency or re-implement a lighter AST-diff-first hook that escalates to tdd-guard's validator only on ambiguity. Bundling minimizes implementation effort and inherits tdd-guard's language reporter ecosystem [26]; re-implementing wins on cost per TDD cycle and avoids the npm install friction. The recommended path is to bundle tdd-guard as the default, document the AST-first design as an optional low-cost mode, and let users opt in based on their cost profile.
