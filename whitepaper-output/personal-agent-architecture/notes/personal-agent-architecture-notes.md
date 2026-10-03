# personal-agent-architecture — Notes

<!-- Notes for the personal-agent-architecture topic. Organized by question, not source. -->
<!-- Citations are stored in whitepaper/personal-agent-architecture-references.md -->

## General Understanding

### Q1: What is OpenClaw — origin, lineage, creator, adoption, what does it do?

**Identity.** OpenClaw is a free, MIT-licensed, open-source autonomous personal AI agent: "a personal AI assistant you run on your own devices that answers you on the channels you already use" — WhatsApp, Telegram, Slack, Discord, Signal, iMessage, etc. [1][2]. It is a local gateway process running as a background daemon on the user's machine or a VPS, routing every incoming message through an LLM-powered agent runtime that can take real actions (shell, files, browser) [3]. Bring-your-own-API-key: integrates external LLMs (Claude, GPT, DeepSeek); no subscription [1][2].

**Lineage (canonical, per Wikipedia).** Created by Austrian developer Peter Steinberger ("vibe coder"; derived from his prior assistant Clawd/Molty, named after Anthropic's Claude) [1]:
- 2025-11-24: launched as "Warelay"
- 2025-12-03: renamed "CLAWDIS"
- 2026-01-02: renamed "Clawdbot"
- 2026-01-27: renamed "Moltbot" (Anthropic trademark complaint over "Clawd")
- 2026-01-30: final rename "OpenClaw"
Implementation: TypeScript and Swift; skills system with directory-based tool organization; config and history stored locally [1].

**Trajectory.** Crossed 100K GitHub stars within its first week as OpenClaw (late January 2026) [3]; 247K stars / 47.7K forks by 2026-03-02 [1]; 350K+ stars by ~April 2026 per third-party stats [8]. April 2026 stats (third-party, treat as estimates): 38M monthly site visitors, 3.2M active users, 44K+ ClawHub skills, 500K+ running instances; strong adoption in China (Tencent, Baidu, Z.ai integrations; later restricted on government machines) [8][1].

**Governance pivot.** 2026-02-14: Steinberger announced joining OpenAI; simultaneously established the non-profit OpenClaw Foundation to steward the project [1]. (Press framed this as an OpenAI "acquisition" of OpenClaw; the durable fact is creator hire + foundation stewardship.)

### Q2: Core runtime architecture — gateway/daemon, session model, agent loop, model providers

**Gateway = control plane.** A single long-lived Gateway daemon per host is "the traffic controller and source of truth" [7]. It owns all messaging-provider connections (WhatsApp via Baileys, Telegram, Slack, Discord, Signal, iMessage, WebChat), exposes a typed WebSocket API (JSON text frames; `{type:"req"|"res"|"event", id, method, params}`; first frame must be `connect` or hard close), validates frames against TypeBox/JSON Schema, and serves a canvas host over HTTP under `/__openclaw__/canvas/` [5]. Default bind: `127.0.0.1:18789`, WS+HTTP multiplexed on one port [5] (NOTE: this loopback default is the *post-crisis* secure default — see Q4). Three client classes: control-plane clients (macOS app, CLI, web UI, automations), nodes (macOS/iOS/Android/headless devices declaring `role: node` with capabilities), and WebChat [5].

**Trust/pairing.** Device identity on every `connect`; challenge-nonce signing; loopback can auto-approve, tailnet/LAN require explicit approval; paired devices get device tokens; remote access via Tailscale/VPN/SSH tunnel — the project deliberately avoids exposing the port publicly [5]. Side-effecting RPC methods require idempotency keys [5]. Events are not replayed; clients must refresh on gaps [5].

**Agent loop.** Intake → context assembly → model inference → tool execution → streaming replies → persistence [6][7]. Context assembly: workspace resolved (sandboxed runs redirect to sandbox roots), skills snapshot loaded and injected into env+prompt, bootstrap files injected into system prompt, session write lock acquired ("process-aware and file-based"), system prompt built from base + skills + bootstrap + per-run overrides "with model-specific limits and compaction reserve tokens enforced" [6]. Plugin hooks intercept at `before_model_resolve`, `before_prompt_build`, `before_tool_call` (can block execution) [6]. Tool calls emit start/update/end events; results sanitized for size/images before logging [6]. `NO_REPLY` token suppresses replies [6]. Timeouts: agent.wait 30s default; agent runtime 48h default; model idle 120s [6].

**Session model.** Sessions are the unit of state: one primary DM session per agent (`main`), separate sessions per group/channel/thread, optional "secure DM mode" isolating DMs per sender [7]. Transcripts persist as JSONL at `~/.openclaw/agents/<agentId>/sessions/<SessionId>.jsonl` [7]. Command Queue: lane-aware FIFO, one active run per session, parallel across sessions; modes steer/followup/collect/interrupt (steer injects into a live run at tool boundaries; collect coalesces messages into one follow-up turn) [6][7].

**Autonomy triggers (five event sources).** User messages, heartbeats (default 30-min cadence), cron schedules, webhooks, internal hooks [7].

**Key principle.** "OpenClaw doesn't 'learn' by changing model weights. It maintains continuity by reading and writing state on disk" and re-injecting it each turn [7].

### Q3: Memory and persona — SOUL.md, IDENTITY.md, MEMORY.md, daily notes, workspace, compaction

**Workspace = the agent's "soul on disk."** Agents live in plain-text files in a workspace folder (default `~/.openclaw/workspace`); at session start OpenClaw assembles identity, behavior rules, memory, and schedule from these files [9][10]. Core principle: "if it's not written to a file, it doesn't exist" [10] — continuity is disk I/O, not weights [7].

**Bootstrap files (always loaded, survive compaction)** [10][11]:
- **SOUL.md** — personality, tone, ethical boundaries, the presence the agent shows every time
- **IDENTITY.md** — role-based identity definition
- **USER.md** — the human's projects, priorities, preferences, technical environment
- **AGENTS.md** — operational rules, workflow decisions, tool conventions, behavioral constraints
- **TOOLS.md** — tool specs and usage guidelines, environment-specific notes
- **MEMORY.md** — durable facts, decisions, learned/mistake-corrected preferences; loaded at start of every DM session
- **HEARTBEAT.md** — recurring automated tasks
- **BOOTSTRAP.md** — first-run system initialization parameters

Sub-agent sessions receive only AGENTS.md + TOOLS.md — persona and private memory filtered out to keep sub-agent context lean and avoid leaking user data [10]. MEMORY.md loads in main/DM sessions but NOT shared/group contexts (privacy) [9][11].

**Two-layer recall.** MEMORY.md = curated long-term layer ("smaller and calmer... stuff you want to keep true over time"); `memory/YYYY-MM-DD.md` (optionally `-<slug>`) daily notes = working layer ("running context and observations"), with today's + yesterday's auto-loaded [9][11]. Daily notes are indexed for search but not bootstrap-injected [9]. Optional DREAMS.md: background "dreaming" consolidation promotes short-term signals into MEMORY.md gated on "score, recall frequency, and query diversity"; outputs logged for human review [9].

**Budgets.** Per-file default 20,000 chars; combined bootstrap ceiling 150,000 chars (~50K tokens) [10][11]. Community best practice: keep each file 10–15K [11]. `/context list` verifies actual injection and detects truncation [10]. If MEMORY.md exceeds budget, disk file stays intact but a truncated copy is injected into context [9].

**Compaction.** Two pathways [10]: (1) maintenance compaction (ideal) — pre-compaction memory flush fires automatically, "a silent turn that reminds the agent to save important context to memory files" before summarizing [9]; (2) overflow recovery (dangerous) — context limit hit, emergency compression with no prior save, maximum info loss. Config: `reserveTokensFloor: 40000` (default 20K often too tight), `memoryFlush.enabled: true`, `softThresholdTokens: 4000` [10].

**Search/retrieval (`memory-core` plugin).** `memory_search` (hybrid keyword + embeddings) and `memory_get` (file/line-range read) [9]. Two backends [10]: Track A built-in local hybrid — `ggml-org/embeddinggemma-300m`, default vector weight 0.7 / text 0.3; Track B QMD backend indexing Obsidian vaults, session transcripts, external docs (BM25 or semantic). Embedding providers: OpenAI (default), Gemini, Voyage, Mistral, Ollama, Bedrock [9].

**Three failure modes** [10]: never-stored (lived only in chat), compaction-loss (summarization dropped nuance/constraints), session-pruning (tool results trimmed in-memory; on-disk transcript fine but invisible to the current request). Recommended practice: store durable rules in MEMORY.md/AGENTS.md not chat; verify the pre-compaction flush with adequate buffer; add a "search memory before non-trivial work" retrieval protocol to AGENTS.md; weekly distillation of daily logs into MEMORY.md to prevent bootstrap bloat [10].

> CONTRADICTION/SCOPE FLAG: the *official* memory doc page [9] names only MEMORY.md + daily notes + DREAMS.md + the memory-core tools; the fuller SOUL/IDENTITY/USER/AGENTS/TOOLS/HEARTBEAT/BOOTSTRAP inventory is consolidated from community guides [10][11]. They are consistent (bootstrap files and memory files are different subsystems) but the named-eight inventory is community-documented, not all on one official page. This is the exact file set CommandClaw-vault mirrors (SOUL.md, IDENTITY.md, USER.md, AGENTS.md, TOOLS.md, MEMORY.md, HEARTBEAT.md, BOOTSTRAP.md).

### Q4: Security model and documented failures

**Designed model.** Pairing codes + Gateway tokens, challenge-nonce device signing, secure DM mode (per-sender isolation), sandboxing, loopback-preferred binding, idempotency keys on side-effecting RPC [5][7]. The intended threat posture is reasonable; the *shipped defaults and pace* were not.

**Exposure scale (independent scans; numbers vary by scanner/date, all large):**
- Feb 2026: 135,000+ publicly exposed instances, 63% without auth; 12,000+ confirmed RCE-exploitable [12][13]. Widely attributed to default bind `0.0.0.0:18789` (all interfaces) on cloud VPS. [CONTRADICTION resolved: docs [5] now say `127.0.0.1`; secure loopback default was a *fix* in v2026.2.25 — pre-patch builds and many VPS one-click images bound to all interfaces. Date-stamp the claim.]
- Maor Dayan: 42,665 exposed (passive scan); of 5,194 verified, 93.4% had critical auth-bypass [12]. Bitsight: 30,000+ concurrent [12]. SecurityScorecard STRIKE: 42,900 unique IPs with exposed control panels, 15,200 RCE-vulnerable [12].
- 2026-03-05 public watchboard: 258,305 exposed instances across dozens of countries [12].

**Advisory/CVE volume.** Joel Gamblin's tracker (jgamblin/OpenClawCVEs): 137 advisories between 2026-02-02 and 2026-04-04 (~1 every 15 hours); 5 received formal NVD CVE IDs [13]. ("512 vulnerabilities" — the figure in CommandClaw's VISION.md — was NOT directly confirmed here; substantiated counts are 90–137 advisories depending on source/window [12][13]. Treat "512" as needing a primary citation or downward revision. FLAG.)

**Named CVEs** [13]:
- CVE-2026-25253 "ClawBleed" — RCE via WebSocket XSS, CVSS 8.8, Feb 2026, actively exploited. (Some outlets call the one-click WebSocket hijack "ClawJacked"; naming overlaps — minor inconsistency between [12] and [13].)
- CVE-2026-27002 — privilege escalation, 2026-02-27.
- CVE-2026-28472 "ClawJacked" — WebSocket auth bypass, fixed in 2026.2.2.
- CVE-2026-32922 — priv-esc → RCE, CVSS 9.9, 2026-03-29 (any paired device → full admin/RCE via a single API call), patched within 13 days.
- CVE-2026-33579 — priv-esc via pair path, 2026-04-01, patched within 2 days.

**Supply chain (ClawHub marketplace — no skill signing, no mandatory review).** Koi Security early Feb: 341 malicious skills of 2,857 reviewed, incl. the #1 most-downloaded [12]. Mid-Feb: escalated to 1,184 malicious (one attacker uploaded 677) [12]. Cisco: 26% of analyzed skills contained vulnerabilities; third-party skills performed data exfiltration + prompt injection without user awareness [1][7]. Microsoft Threat Intelligence: Cline CLI npm package silently installed OpenClaw for ~8 hours on 2026-02-17 [12].

**Public reckoning.** 2026-02-20 Karpathy (3.3M views): OpenClaw is "400K lines of vibe coded monster that is being actively attacked at scale" [12]. 2026-02-23 Meta's Summer Yue: her agent deleted her entire inbox while ignoring "STOP" [12] — the canonical machine-speed-runaway anecdote. Late Feb: Belgium national cyber center advisory; Cisco called personal AI agents "a security nightmare" [12]. March: China restricted OpenClaw on government/state-enterprise machines [1].

**Response.** v2026.2.25: ClawJacked patch + mandatory authentication + loopback-only default binding [12] — secure defaults arrived reactively, ~1 month after mass exposure went public. Foundation + accelerating patch cadence (2–13 day turnarounds by late March) [13] show governance maturing post-crisis.

### Summary

OpenClaw is a single-daemon, file-state, channel-fronted personal agent: a Gateway control plane owns connections + sessions + routing and drives a disk-persisted agent loop (intake → context assembly from bootstrap+memory files → inference → tools → stream → persist), with five autonomy triggers (messages, 30-min heartbeat, cron, webhooks, hooks) [5][6][7]. Memory is the spine and the most-copied idea: bootstrap files (SOUL/IDENTITY/USER/AGENTS/TOOLS/MEMORY/HEARTBEAT/BOOTSTRAP) always in context, daily notes + MEMORY.md for durable recall, hybrid embedding search, and a pre-compaction flush to fight context loss [9][10][11]. The same properties that made it viral (local, file-transparent, channel-native, skill-extensible, bring-your-own-key) created its security catastrophe: shipped with a public-interface bind and an unsigned skill marketplace, it produced 135K+ exposed instances, 100+ advisories in two months, and headline machine-speed-harm anecdotes [12][13]. Durable lesson for a redesign: the agent loop and file-memory pattern are right and worth copying; credential handling, default network posture, and supply-chain trust were the failures — exactly the seams a control-plane-first redesign must own. Steinberger→OpenAI + the OpenClaw Foundation (2026-02-14) [1] mark the handoff from solo-vibe-coded project to stewarded ecosystem.

---

## Deeper Dive

### Subtopic A: Autonomy & scheduling (the proactive engine)

**Heartbeat = judgment loop.** Periodic main-session turn (~30 min) that batches checks (inbox, calendar, notifications) in one agent turn with full main-session context [14]. Reads `HEARTBEAT.md` checklist or `tasks:` blocks; stays silent unless something needs attention; replies `HEARTBEAT_OK` when nothing actionable and OpenClaw auto-suppresses that so it never reaches the user's phone [14]. Does NOT create task records and does NOT extend daily/idle session-freshness resets [14]. Skips cleanly: empty file → `empty-heartbeat-file`, nothing due → `no-tasks-due`. Defers while cron work is active/queued (`heartbeat.skipWhenBusy`) [14].

**Cron = clockwork.** Gateway's built-in persistent scheduler: cron expressions + one-shot reminders + webhook triggers [14]. ALWAYS creates task records (auditable via `openclaw tasks list` / `openclaw tasks audit`) [14]. Delivers output to chat channel, webhook, or silent; runs in isolated OR shared session context [14]. Use cron for exact-timing/recurring (daily briefing, weekly report, scheduled publish); use heartbeat for awareness/judgment (inbox monitoring, memory maintenance, health checks) [14][20].

**Hooks = event-driven.** Fire on lifecycle events (`/new`, `/reset`, `/stop`), session compaction, gateway startup, message flow; auto-discovered from directories, managed via `openclaw hooks` [14]. Plugin hooks additionally intercept in-process at tool-call / prompt / message / lifecycle boundaries (`before_tool_call` can block) [6][14].

**Five autonomy triggers total:** messages, heartbeat, cron, webhooks, hooks [7]. **Safety:** "standing orders" (boundaries injected into every session) can combine with cron for time-based enforcement of autonomous-action limits [14] — but note this is prose-level steering, not a hard gate; the Summer Yue inbox-deletion incident (Q4) shows prose boundaries are not sufficient for irreversible actions. This is the seam where a redesign should add deterministic confirmation gates.

### Subtopic B: Skills/plugin ecosystem & MCP

**Skill = markdown + frontmatter.** Each skill is a directory with a `SKILL.md` (Markdown + YAML frontmatter) [15][20]. Frontmatter: `name`, `description` (used as search/UI summary, extracted at publish), `version` (semver); runtime gates under `metadata.openclaw`: `requires.env`/`requires.bins`/`requires.anyBins`/`requires.config`, `primaryEnv`, `envVars`; display/behavior: `emoji`, `homepage`, `os`, `always` (always-active), `skillKey`, `install` (brew/node/go/uv dependency specs) [15]. Bundle limit 50MB; embedding scope SKILL.md + ~40 non-.md files; slug `^[a-z0-9][a-z0-9-]*$`; all skills MIT-0; no paid skills [15]. Security: ClawHub "checks that what your skill declares matches what it actually does" — declared-vs-actual mismatches trigger review flags [15] (this static check is the post-crisis response to the 341→1,184 malicious-skill problem; still no mandatory signing).

**ClawHub = the registry.** Public skill registry (publish/version/search), CLI-friendly API, vector search, moderation hooks [20]. 13,700+ skills by late Feb 2026 [20]; third-party mirrors cite far higher (VoltAgent "5,400+ filtered," other stats 44K+ — counts inflated by spam/dupes, consistent with the supply-chain problem).

**MCP is the actuator.** 65%+ of active OpenClaw skills wrap an underlying MCP server [20]. Division of labor: "Skills tell the agent what to do; MCP servers give it the ability to actually do it" [20]. MCP servers are portable (Claude Desktop, Cursor, VS Code, any MCP host); skills are OpenClaw-specific. Recommended pattern: build an MCP server for capability + wrap in a SKILL.md for workflow logic [20]. → The SKILL.md format is materially the same shape as Claude Agent Skills (name/description frontmatter + markdown body), which is why CommandClaw-skills can claim cross-ecosystem compatibility.

### Subtopic C: Comparable systems (competitive landscape)

**Letta / MemGPT — DB-managed self-editing memory (the contrast model).** Letta (formerly MemGPT) frames the LLM as an OS managing its own memory [18]. Memory hierarchy: core memory blocks (labeled — `human`, `persona`, `knowledge` — always injected, size-limited, each a DB row with `block_id`) + recall + archival (out-of-context, DB, retrieved by search) [18]. The agent self-edits blocks via tools (e.g. a `rethink` tool replaces a block's value); block values are just strings, so lists/dicts can be stored serialized [18]. Context window is **compiled from DB state** before each request [18]. Shared blocks across agents enable collaborative memory [18]. Letta V1 deprecated MemGPT's heartbeat + `send_message` tool in favor of native reasoning + direct assistant messages — explicitly moving toward Claude-Code-like patterns; trade-off: agents lose the heartbeat self-trigger concept [19].

**The architectural fork.** OpenClaw/CommandClaw = **files are memory** (markdown bootstrap files always injected; human-readable; git-diffable; edited by file tools). Letta = **DB blocks are memory** (rows the agent edits via tools; queryable; API-addressable; not human-browsable without the app). Files win on transparency, auditability, vendor independence, and Obsidian/git interop; DB blocks win on programmatic addressing, multi-agent sharing, and structured querying. CommandClaw's git-native bet is the files side taken to its logical end (the repo IS the control plane); the cost it must overcome is that file memory has weaker structured-retrieval than DB blocks — which is exactly what commandclaw-memory (LanceDB+BM25 over the wiki) is meant to add back.

**Claude Code / AGENTS.md / Karpathy LLM-wiki — the vault-agent lineage.** Karpathy's principle: don't script steps in CLAUDE.md, write success criteria and let the loop run [21]. His LLM-wiki concept = structured markdown as substrate + capable agent as interface; "your Obsidian vault is just a folder of markdown files," the agent reads structure and writes back [21]. AGENTS.md/CLAUDE.md are the cross-tool standard (Claude Code, Codex, Cursor, Gemini, OpenCode, Aider, Copilot, and OpenClaw all consume AGENTS.md / Agent-Skills format) [21]. Multiple git-native memory layers for Claude Code already exist (zero-dep bash, privacy-first) and "claude-obsidian" implements Karpathy's LLM-wiki directly [21]. → CommandClaw sits in this exact lineage; its differentiation is NOT the file-memory idea (commoditized) but the security-hardened gateway + single-writer validated memory service around it.

### Subtopic D: Security hardening patterns for agent gateways

**Phantom token pattern (the credential-isolation primitive).** Origin: Luke Hinds (Sigstore creator) in `nono`, an open-source sandbox for AI coding agents [17][16]. Mechanic: agent never holds the real credential; it gets a short-lived, tightly-scoped token meaningless outside a credential-injection proxy [16]. Proxy (reverse proxy, localhost-bound) validates the phantom token (TTL + agent-identity binding + operation scope), substitutes the real credential from a vault, makes the upstream call, strips credentials from the response [16]. Scoping layers: operation (e.g. read-only on a dataset), session binding (expires with session, no rotation cleanup), identity binding, TTL [16]. Blast radius: a leaked real key works everywhere/any-IP/any-op; a leaked phantom token works only through the (now-dead) proxy, scoped ops, within TTL, from the bound identity [16]. Beats rotation: rotation shortens the window; phantom tokens eliminate it (agent never holds the key) [16].

**Maps directly to MCP + gateway RBAC.** For MCP agents the pattern is identical: point MCP transports at the proxy with phantom-token auth; tool invocations get credential injection at the gateway layer, not at agent init [16]. Every proxy-mediated call emits attribution logs (which identity, endpoint, operation, timestamp) → enables RBAC retrospectives + session-scoped revocation [16]. → This is EXACTLY commandclaw-mcp's design (phantom tokens, hourly rotation, Argon2id-at-rest, Cerbos RBAC, per-call mediation) and commandclaw-gateway's virtual keys (`sk-cc-*`). The pattern is industry-validated and independently converged on (nono, API Stronghold, Brex's CrabTrap, CommandClaw) — strong signal the architecture is correct and the wedge is real.

### Summary

The Deeper Dive confirms a clean separation between the parts of the personal-agent pattern that are commoditized and the parts that are still contested. Commoditized: the agent loop, the file-based bootstrap/memory inventory, the markdown-skill format, the heartbeat/cron/hooks autonomy triggers — all of these are well-documented, cross-tool standard (AGENTS.md / Agent Skills), and present in Claude-Code-vault agents and Karpathy's LLM-wiki lineage that CommandClaw already sits in [14][15][C2-search]. Contested / still-valuable: (1) structured retrieval over file memory — where Letta's DB-block model is the benchmark CommandClaw-memory must match with LanceDB+BM25 [18][19]; (2) credential isolation + tool-call mediation — where the phantom-token/credential-proxy pattern is industry-converged (nono, API Stronghold, CrabTrap) and is precisely commandclaw-mcp/gateway's design [16][D-search]; and (3) deterministic safety gates on irreversible autonomous actions — the unsolved seam that OpenClaw's prose "standing orders" failed to cover (Summer Yue) [12][14]. For CommandClaw the takeaway is sharp: do not re-litigate the file-memory pattern (it's settled and copied), invest the differentiation budget in the mcp credential proxy (validated, no incumbent) and the validated-memory retrieval layer (the one thing files do worse than Letta's DB blocks).

