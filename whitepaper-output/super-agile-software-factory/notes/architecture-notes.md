# super-agile-software-factory — Architecture Notes

## Questions

### Q1: What system components make up a super-agile factory end-to-end, and how do the agent harness, context store, scenario bank, DTU, and satisfaction evaluator interact?

The super-agile (dark) software factory as instantiated by StrongDM in early 2026 is a closed-loop system in which specifications flow in and converging code flows out — with no human touching the artefacts in between [ARCH-1][ARCH-2]. The canonical components are:

**Agent Harness (Attractor).** The execution engine that drives a coding agent through discrete, non-interactive turns. StrongDM calls theirs the Attractor: a markdown-native spec that can be injected into any LLM-based coding agent. Anthropic's engineering team formalizes the pattern as Initializer + Coding Agent: the first context-window session creates orientation artefacts (init.sh, progress files, a feature-list JSON), and subsequent sessions pick up that structured state and work on one feature at a time [ARCH-3]. LangChain's taxonomy distinguishes three layers — framework (LangChain), runtime (LangGraph), harness (DeepAgents / Claude Code) — where the harness is the highest-level opinionated shell that arrives "batteries included" with tool access, default prompts, and lifecycle management [ARCH-4]. The key harness responsibilities are: context window management, tool-call dispatch, failure recovery, per-session state handoff, and safety boundary enforcement. Building this from scratch realistically takes four to six months of senior engineering time; Manus reportedly spent six months and five rewrites [ARCH-4].

**Context Store (cxdb).** The factory's durable memory layer. StrongDM's cxdb is an immutable DAG-based store written in Rust/Go/TypeScript (16k/9.5k/6.7k lines at release) [ARCH-2][ARCH-5]. Every conversation turn is an immutable node with a pointer to its parent, forming a content-addressed append-only graph. Branching is O(1): a new context head pointing at any existing turn. The context store is deliberately not a general database — it provides no query language, optimising instead for append-dominant workloads with p50 < 1ms appends [ARCH-5]. Agents are handed read-only snapshots; only the harness kernel writes. This enforces a zero-trust execution boundary consistent with the Decision Intelligence Runtime pattern [ARCH-6].

**Scenario Bank.** Behavioural specifications stored outside the codebase, visible to evaluators but invisible to the code-generating agents. The holdout-set analogy from ML is deliberate: if agents can see the scenarios, they will game them [ARCH-1][ARCH-7]. Scenarios are end-to-end user stories that an LLM can interpret flexibly, in contrast to brittle unit tests. The Infralovers deep-dive on Level 4 architecture further specifies that the harness orchestrates through a directed-graph phase sequence (parse_spec → generate_code → run_scenarios → evaluate) defined in Graphviz DOT syntax, keeping sequencing logic deterministic and human-controlled while leaving LLM reasoning to the edges [ARCH-7].

**Digital Twin Universe (DTU).** Behavioural clones of every third-party integration — Okta, Jira, Slack, Google Docs/Drive/Sheets — built from API contracts and observed edge cases and validated against live services until divergence stops [ARCH-1][ARCH-8]. The DTU enables validation at volumes that exceed production rate limits, and lets the factory exercise failure modes that are impossible or dangerous to trigger against live services. Three engineers maintain the twin corpus; when an upstream service evolves, twins lag until manually updated — a critical maintenance surface [ARCH-7].

**Satisfaction Evaluator.** A probabilistic LLM-as-judge layer that replaces boolean test pass/fail. The metric is: "of all observed trajectories through all scenarios, what fraction likely satisfies the user?" [ARCH-1]. This acknowledges that agentic software under test inherently has non-deterministic trajectories; measuring a single green run is epistemically insufficient. The evaluator sits downstream of the DTU execution loop and feeds a convergence signal back to the harness.

**Interaction topology.** NLSpec + scenarios → Attractor harness → code generation (LLM calls, tool use) → cxdb (turn-by-turn persistence) → DTU execution → satisfaction evaluator → convergence signal → Attractor (next iteration). Human authorship is concentrated entirely upstream in spec and scenario writing; the loop below that line is unattended.

### Q2: What are real-world build-vs-buy options for each architectural component (agent runtimes, spec stores, DTU clones, evaluators), and which are commodity vs differentiated?

**Agent Runtimes / Harnesses**

The market has stratified. Commodity runtimes (durable execution, state persistence, streaming) are now off-the-shelf: LangGraph (Python, explicit state-machine graph, production-ready), OpenAI Agents SDK (minimal boilerplate, handoffs, Python-first), Claude Agent SDK / Claude Code (released September 2025, battle-tested harness with automatic context compaction, filesystem, web search, computer use; powers Claude Code itself) [ARCH-3][ARCH-9]. For TypeScript teams, Mastra and Vercel AI SDK dominate; Mastra ships native MCP support and built-in memory [ARCH-10]. Inngest Agents provides durable step execution on top of its event-driven background functions platform, useful when you need guaranteed-once semantics. AutoGen (Microsoft) and CrewAI suit multi-agent role delegation patterns; CrewAI has the lowest boilerplate for rapid prototyping, LangGraph the highest control for production state machines [ARCH-10].

**Verdict:** Runtime is commodity. Buy. The differentiation is in harness design — the opinionated shell on top. That layer is still largely bespoke per domain. The LangChain taxonomy confirms harnesses are the least commoditised tier [ARCH-4].

**Spec / Context Stores**

Off-the-shelf options are immature. Most teams use SQLite conversation logs, Redis for ephemeral session state, or Postgres with pgvector for hybrid RAG. None of these provide native branching, content-addressed deduplication, or turn-level type awareness. cxdb (Apache 2.0, self-hosted) is the reference implementation of the immutable DAG pattern [ARCH-5]. For teams not willing to operate cxdb, the closest commodities are: Zep (structured memory extraction with entity graphs), Mem0 (hybrid vector + graph + key-value memory), or a custom Postgres schema with a parent_turn_id FK to simulate the DAG. The CMV paper (arxiv 2602.22402) proposes snapshot/branch/trim primitives as a formalisation that could be implemented atop any backend [ARCH-11].

**Verdict:** Differentiated. If agent replayability and branch-from-any-point debugging matter, cxdb or a purpose-built DAG store is worth the operational overhead. For simpler agents, Zep or Mem0 are serviceable buy options. Rolling your own SQLite log is technically buy (commodity tooling) but architecturally a dead-end as agent complexity grows.

**DTU Clones**

No commercial product ships a pre-built Digital Twin Universe for SaaS integrations. Teams must build. Options range from enhanced WireMock/Mockoon HTTP record-replay setups (shallow mocks, miss state and error cascades) to full behavioural twins hand-coded against API contracts. AI-assisted twin generation — using the target service's OpenAPI spec as ground truth and an LLM to generate stateful handlers — is the emerging practice as of 2026 [ARCH-7]. StrongDM's three-engineer twin maintenance team is the realistic staffing floor. Cloud-based contract testing (Pact, Specmatic) provides a partial buy option for synchronous REST contracts but does not model asynchronous webhooks, rate-limit behaviour, or auth-flow edge cases at the fidelity the DTU requires.

**Verdict:** Differentiated, build-required. No viable buy option exists at production fidelity. Start with two to three critical integrations; validate maintenance burden before scaling.

**Satisfaction Evaluators**

Commercial platforms: Braintrust (best-in-class LLM-as-judge automation, Loop agent blocks CI/CD on quality regression, TypeScript-first, used by Notion/Stripe/Vercel, $249/month Pro) [ARCH-12]. LangSmith (deep LangChain integration, auto-instrumentation, Python-centric, per-trace pricing scales badly at volume) [ARCH-12]. Weights & Biases Weave (strong for ML teams already in W&B, multi-step agent trace analysis, experiment tracking integration) [ARCH-13]. Open-source / self-host: Langfuse (MIT, 19k GitHub stars, full LLM-as-judge open-sourced June 2025, strong for regulated industries with data residency requirements) [ARCH-12]. Arize Phoenix (open-source, best-in-class RAG debugging and production monitoring, evaluation is secondary to observability).

DIY evaluators using raw LLM API calls (OpenAI, Claude, Gemini as judges) with custom rubrics are viable for teams with unique domain-specific criteria that no platform can encode. DSPy's compilation-based approach (optimise prompts against a labelled metric) offers an alternative angle: instead of judging outputs post-hoc, it optimises the agent's prompting to maximise a scorer function.

**Verdict:** Buy Braintrust if you need regression blocking in CI and fast time-to-value. Self-host Langfuse if data residency or open-source auditability is a constraint. DIY only when your satisfaction rubrics are domain-unique and no off-the-shelf scorer covers them. Evaluator infrastructure built from scratch typically exceeds $500K in year-one engineering cost [ARCH-12].

### Q3: How do immutable DAG context stores differ from conversation logs / RAG, and why does this matter for agent determinism and replayability?

**The flat-log problem.** Conventional approaches store agent history as an append-only table of (role, content, timestamp) rows in SQLite or Postgres, or as a vector embedding corpus for RAG retrieval. Three failure modes emerge at factory scale. First, there is no branching: exploring an alternative agent trajectory requires copying the entire conversation or accepting a linear overwrite. Second, there is no content-addressed deduplication: if a 500KB tool output appears in twenty parallel agent runs, it is stored twenty times. Third, replay is a sequential scan with no structural guarantees — if the schema changes, historical replays silently degrade. Conversation logs are noise at scale; they are not knowledge representations [ARCH-14].

**The DAG model.** cxdb models every turn as an immutable node with a typed payload hash pointing into a content-addressed blob store (BLAKE3-256), a parent_turn_id linking to its predecessor, and a depth counter [ARCH-5]. Context heads are mutable pointers to current turn tips; everything below is append-only. Branching is constant-time: create a new head pointing at any existing turn. The CMV paper (Contextual Memory Virtualisation) formalises this as snapshot (capture state at point T), branch (create independent path from T), and trim (structurally lossless token reduction that preserves all user/assistant content verbatim, achieving up to 86% token reduction) [ARCH-11].

**Why this matters for determinism.** LLM agents are non-deterministic at the model sampling layer but can be made architecturally deterministic at the state-transition layer. Given the same turn DAG root and the same model checkpoint (temperature=0), the same tool sequence is reproducible. The DAG provides the substrate for this: walking the parent chain from any turn_id reconstructs the exact input context that produced the next model call. This is the foundation of time-travel debugging — you can re-run any intermediate agent state without re-executing the full trajectory [ARCH-5][ARCH-6].

**Why this matters for replayability.** The Decision Intelligence Runtime pattern treats context snapshots as read-only inputs to agent reasoning and enforces JIT state verification: before any side-effecting action, the runtime compares the agent's stale snapshot against live system state and aborts if drift exceeds threshold [ARCH-6]. This only works if the snapshot is both immutable (the agent cannot have modified its own context) and addressable (the harness can re-materialize the exact snapshot for audit). A flat mutable SQLite log fails both conditions.

**RAG comparison.** RAG retrieves semantically similar chunks from an unordered corpus; it does not model conversation structure, causality, or agent state transitions. For agentic use cases, the 2026 practitioner consensus (Karpathy, Zep, Mem0) is that vanilla RAG fails: it introduces retrieval noise and cannot reconstruct the ordered decision sequence that produced an outcome [ARCH-14]. Graph RAG (knowledge graph traversal) closes some of this gap for entity-relationship queries but still does not provide the turn-level audit trail or O(1) branching that a DAG store provides.

**Actionable recommendation.** Adopt an immutable DAG store from the start if your agents run longer than a single context window, execute side-effecting tools, or need compliance-grade auditability. cxdb is the reference open-source implementation. The additional operational complexity (Rust binary, custom binary protocol) is worth bearing if your factory runs thousands of agent trajectories daily. For smaller-scale deployments, a Postgres table with parent_turn_id and a content-hash column captures 80% of the semantics at lower ops burden, but you forfeit the O(1) branch and native dedup optimisations.

**Edge case and contradiction flag.** The CMV paper's trim primitive claims "structurally lossless" reduction. However, cxdb v1 explicitly does not provide a trim operation — it stores everything verbatim [ARCH-5]. Contradicts [ARCH-11]: CMV's lossless trim assumes semantic equivalence of compressed representations, which cxdb's designers have implicitly rejected by deferring trim to caller-side context compaction (e.g., the Claude Agent SDK's automatic compaction layer). These are complementary rather than competing, but the distinction matters: trim at the harness level (lossy, invisible to the store) versus trim at the store level (lossless, auditable) have different compliance properties.

---

## Summary

The super-agile software factory is not a single product but an integration of five architectural tiers: a spec/scenario authoring surface (human-controlled), an agent harness (increasingly off-the-shelf from LangGraph, Claude Agent SDK, or OpenAI Agents SDK), a durable context store (the least commoditised tier, with cxdb as the current reference implementation of the DAG pattern), a Digital Twin Universe (bespoke, build-required, maintenance-intensive), and a probabilistic satisfaction evaluator (commercial buy recommended: Braintrust for CI integration, Langfuse for open-source control). The system's defining property is the shift of human editorial authority entirely upstream — into specs and scenarios — while the downstream execution loop is unattended and non-interactive.

The context store is the architectural linchpin that most teams underinvest in. Flat conversation logs are structurally inadequate for multi-session agents: they cannot branch, cannot deduplicate, and cannot provide the immutable audit trail required for JIT state verification and compliance. An immutable DAG store converts a stochastic agent trajectory into a deterministic, addressable, time-travel-debuggable artefact. This is a precondition for the satisfaction evaluator to function correctly: you cannot measure "what fraction of trajectories satisfy the user" without a reliable record of what trajectories actually occurred.

The DTU is the highest-cost and least-transferable component. No buy option exists at production fidelity. The economic model only makes sense above a certain scale (StrongDM's reference point is $1,000/engineer/day in token spend, with twin maintenance requiring three dedicated engineers). For teams below that scale, enhanced contract testing (Pact, Specmatic) combined with selective chaos injection against staging environments is a viable intermediate position before committing to full behavioural twin infrastructure.

---

## References

[ARCH-1] StrongDM. "StrongDM Software Factory." *factory.strongdm.ai*. 2026. URL: https://factory.strongdm.ai/. Accessed: 2026-04-18.

[ARCH-2] Willison, Simon. "How StrongDM's AI team build serious software without even looking at the code." *simonwillison.net*. 2026-02-07. URL: https://simonwillison.net/2026/Feb/7/software-factory/. Accessed: 2026-04-18.

[ARCH-3] Anthropic. "Effective Harnesses for Long-Running Agents." *Anthropic Engineering Blog*. 2026. URL: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents. Accessed: 2026-04-18.

[ARCH-4] LangChain. "Agent Frameworks, Runtimes, and Harnesses." *LangChain Blog*. 2026. URL: https://www.langchain.com/blog/agent-frameworks-runtimes-and-harnesses-oh-my. Accessed: 2026-04-18.

[ARCH-5] StrongDM. "cxdb NEW_SPEC.md." *GitHub (strongdm/cxdb)*. 2026. URL: https://github.com/strongdm/cxdb/blob/main/NEW_SPEC.md. Accessed: 2026-04-18.

[ARCH-6] O'Reilly Radar. "The Missing Layer in Agentic AI." *O'Reilly*. 2026. URL: https://www.oreilly.com/radar/the-missing-layer-in-agentic-ai/. Accessed: 2026-04-18.

[ARCH-7] Infralovers. "Dark Factory Architecture: Level 4." *infralovers.com*. 2026-02-22. URL: https://www.infralovers.com/blog/2026-02-22-architektur-patterns-dark-factory/. Accessed: 2026-04-18.

[ARCH-8] StrongDM. "Digital Twin Universe." *factory.strongdm.ai*. 2026. URL: https://factory.strongdm.ai/techniques/dtu. Accessed: 2026-04-18.

[ARCH-9] O'Reilly. "Getting Started with Claude Agent SDK." *O'Reilly Live Events*. 2025. URL: https://www.oreilly.com/live-events/getting-started-with-claude-agent-sdk/0642572273255/. Accessed: 2026-04-18.

[ARCH-10] Firecrawl. "Best Open Source Frameworks for Building AI Agents in 2026." *firecrawl.dev*. 2026. URL: https://www.firecrawl.dev/blog/best-open-source-agent-frameworks. Accessed: 2026-04-18.

[ARCH-11] Unknown Author. "Contextual Memory Virtualisation: DAG-Based State Management and Structurally Lossless Trimming for LLM Agents." *arXiv (Cornell University)*. 2026. URL: https://arxiv.org/abs/2602.22402. Accessed: 2026-04-18.

[ARCH-12] Braintrust. "Best LLM Evaluation Platforms 2025." *braintrust.dev*. 2025. URL: https://www.braintrust.dev/articles/best-llm-evaluation-platforms-2025. Accessed: 2026-04-18.

[ARCH-13] AIM Research. "LLM Observability Tools: Weights & Biases, LangSmith 2026." *research.aimultiple.com*. 2026. URL: https://research.aimultiple.com/llm-observability/. Accessed: 2026-04-18.

[ARCH-14] Vectorize.io. "Best AI Agent Memory Systems in 2026." *vectorize.io*. 2026. URL: https://vectorize.io/articles/best-ai-agent-memory-systems. Accessed: 2026-04-18.
