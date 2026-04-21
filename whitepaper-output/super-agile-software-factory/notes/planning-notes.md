# super-agile-software-factory — Planning Notes

## Questions

### Q1: How are specifications structured when they replace source code as the primary human artifact, and what conventions govern spec-driven agentic development?

Spec-driven development (SDD) emerged prominently in 2025 as "a development paradigm that uses well-crafted software requirement specifications as prompts, aided by AI coding agents, to generate executable code" [PLAN-1]. By early 2026 it had become the dominant mode of professional agentic engineering practice, with tools, open standards, and organizational frameworks consolidating around it [PLAN-2].

**Spec as the primary artifact.** The most extreme instantiation is StrongDM's Software Factory, where the Attractor agent's GitHub repository contains only specification documents — no executable code at all [PLAN-3]. Their production system runs three meticulous markdown files of 6,000–7,000 lines of natural-language specification driving 32,000 lines of production Go, Rust, and React [PLAN-4]. BMAD, the most widely adopted open framework for agentic agile, formalizes this inversion: "source code is no longer the sole source of truth — documentation (PRDs, architecture designs, user stories) is, with code becoming merely a downstream derivative" [PLAN-5].

**Six mandatory elements.** A spec for an AI agent must contain six elements to function as an executable contract [PLAN-6]:
1. **Outcomes** — concrete end states, not feature names
2. **Scope boundaries** — explicit in-scope and out-of-scope lists; omission is not exclusion for agents
3. **Constraints and assumptions** — tech stack decisions, API limits, performance thresholds
4. **Prior decisions** — already-chosen databases, libraries, or schemas to prevent redundant selection
5. **Task breakdown** — discrete sub-tasks enabling parallel execution and verifiable checkpoints
6. **Verification criteria** — quantified thresholds, explicit behaviors, testable conditions — never subjective language like "intuitive" or "fast"

**File and format conventions.** The GitHub Blog's reference implementation uses a four-file structure: `README.md` for user-facing docs, `main.md` as the executable spec, `compile.prompt.md` as the agent instruction, and generated source as the downstream artifact [PLAN-7]. Terminology must be consistent throughout — a linting step should enforce one verb per concept (fetch not get/pull/retrieve) to prevent agent misinterpretation [PLAN-7]. Amazon's Kiro IDE formalizes this further with three spec layers: Requirements specs using **EARS (Easy Approach to Requirements Syntax)** notation for acceptance criteria; Technical Design specs including data-flow diagrams, TypeScript interfaces, and database schemas; and Task specs with sequenced dependencies, each linked to requirements and pre-wired with unit tests and integration tests [PLAN-8].

**Steering files vs. spec files.** Kiro introduced an important structural distinction: **steering files** are project-wide markdown documents encoding organizational standards (compliance requirements, security patterns, accessibility rules) that apply to all agent sessions, while **spec files** are feature-scoped [PLAN-8]. GitHub Spec Kit's `constitution.md` serves the same role — non-negotiable organizational principles that anchor all subsequent spec authoring [PLAN-9].

**AGENTS.md as the cross-platform layer.** Donated to the Linux Foundation's Agentic AI Foundation on December 9, 2025 by OpenAI and Anthropic, `AGENTS.md` is now an open standard co-authored by Google, OpenAI, Factory, Sourcegraph, and Cursor [PLAN-10]. It sits at the repository root and provides agents with build and test commands, code style rules, security constraints, and commit conventions. Critically, it has no required fields — it is plain Markdown parsed by the agent — but it separates agent-targeted operational context from human README content [PLAN-10].

**Workflow pattern.** The canonical spec workflow is: Specify → Plan → Tasks → Implement, with human review gates between each phase [PLAN-6]. For spec authoring specifically: use the most capable available model (errors in specs propagate through the entire implementation chain), mid-range models for implementation, and fast accurate models for verification against spec criteria [PLAN-6]. Reserve specs for work that would require more than five minutes of focused code review; below that threshold the overhead is not justified [PLAN-6].

**Build recommendation.** For a team standing this up, adopt the three-layer structure: `AGENTS.md` (repo-wide operational constants) + `constitution.md` or steering file (organizational standards) + per-feature `spec.md` files following the six-element template. Store specs under version control alongside code, not in a wiki, so spec and code history are co-auditable.

### Q2: How is scenario authoring practiced as an ML-holdout discipline, and what makes a good end-to-end scenario for a super-agile factory?

**The holdout analogy.** StrongDM's Software Factory introduced the definitive framing: scenarios are "end-to-end user stories stored outside the codebase — functioning as holdout sets similar to model evaluation datasets" [PLAN-3]. The agent builds against NLSpecs but cannot see the validation scenarios during development, exactly as an ML model cannot see its test split during training. After code is generated and converges, scenarios run to reveal whether the system satisfied user intent. The result is not pass/fail — it is **satisfaction**: "of all the observed trajectories through all the scenarios, what fraction of them likely satisfy the user?" [PLAN-11]. This probabilistic framing is essential when the software itself has an agentic component with non-deterministic paths.

**Cem Kaner's foundational definition.** Kaner, who introduced scenario testing formally in 2003, defined the ideal scenario test as having five characteristics: it is **realistic** (drawn from actual customer or competitor situations), **complex** (uses several features and functions), unambiguous in outcome (no disagreement about whether it passed), **motivating** for stakeholders (someone influential will protest if it fails), and **end-to-end** (it checks a full benefit the program is supposed to deliver, not a subsystem) [PLAN-12]. These characteristics remain the correct quality bar for super-agile scenario authoring; the difference in 2026 is that the judge of satisfaction is an LLM evaluator rather than a human tester.

**What makes a good factory scenario.** Synthesizing Kaner [PLAN-12] with StrongDM practice [PLAN-3] and LLM evaluation research [PLAN-13]:

- **Narrative form, not test case form.** Scenarios should read as user stories — "a developer is trying to provision access to a production database under a time-sensitive incident" — not as function signatures with expected return values. This structure is what an LLM evaluator can assess holistically.
- **Multi-step, cross-service.** A scenario must traverse at least two system boundaries to be diagnostic. Single-service scenarios are unit tests; they belong in the coded test suite, not the holdout set.
- **Outcome-graded, not trace-graded.** The evaluator asks "did the user achieve their goal?" not "did the agent call function X before function Y?" Trace-grading locks in implementation details and makes refactoring regress the scenario suite.
- **Authoring outside the development context.** Scenarios must be kept in a separate repository or access-controlled directory — not co-located with specs the agent uses during coding [PLAN-4]. If the agent can read the scenario during implementation, it is no longer a holdout.
- **Coverage of failure modes, not just happy path.** Kaner's original insight — scenarios should expose failures in delivering user benefits, not just confirm that happy paths work — applies directly. A super-agile factory needs adversarial scenarios that probe edge cases (partial failures, retries, degraded-mode behavior) because agents tend to optimize for happy paths specified in the NLSpec [PLAN-12].

**LLM graders for scenario evaluation.** The practical replacement for a QA human evaluating scenario outcomes is an LLM-as-judge with a rubric tied to the scenario's stated user goal [PLAN-13]. Current calibration guidance: an LLM judge needs greater than 80% agreement with human-labeled validation data on the specific task type before it can be trusted as an automated CI gate [PLAN-13]. Below that threshold, route failing scenarios to human review rather than blocking the pipeline. The MINT (Multi-turn Interaction using Tools) benchmark framework, which places models in simulated multi-turn scenarios requiring tool use and feedback response, is the closest public analog to the StrongDM model [PLAN-13].

**The Digital Twin Universe dependency.** High-quality factory scenarios require behavioral clones of external services — StrongDM's Digital Twin Universe provides Go binary clones of Okta, Jira, Slack, and Google Workspace built from public API documentation [PLAN-3]. Without this, scenarios either hit production systems (cost, rate limits, side effects) or are shallow mocks that underspecify behavior. The build recommendation: start with two or three critical integrations and implement twins before scaling the scenario suite, because scenarios without realistic service twins produce satisfaction scores that don't generalize to production [PLAN-4].

**Scenario authoring as a distinct role.** Because scenario quality is the binding constraint on factory output quality, scenario authoring should be treated as a discipline separate from spec writing. The analogy to ML is precise: data scientists who design evaluation sets are distinct from those who design model architectures. In a super-agile team, the scenario author holds domain expertise about real user workflows and adversarial usage patterns, and should not be the same person writing the NLSpec that drives the agent — that separation maintains the holdout integrity.

### Q3: What planning processes and artifacts (roadmaps, epics, PRDs) need to change when the unit of delivery is a spec handed to an agent rather than a ticket handed to a human?

**The fundamental shift.** Traditional agile assumes the planning artifact (ticket, user story) is a communication medium between humans who fill in ambiguity with shared context. A spec handed to an agent cannot rely on that gap-filling — "agents fill gaps differently, and unexpectedly" [PLAN-6]. Every degree of freedom left unspecified in a planning artifact becomes a source of non-deterministic divergence. The planning process must therefore shift its primary output from communication documents to executable contracts [PLAN-14].

**PRD restructuring.** The structural changes to PRDs for agent-driven delivery are well-documented by mid-2026 [PLAN-14][PLAN-15]:

- **From narrative to sequential phases.** Traditional PRDs present features holistically for human comprehension. Agent-optimized PRDs decompose into dependency-ordered phases (database schema before queries, shared utilities before components that use them). Each phase must leave the codebase in a runnable, testable state.
- **Positive statement of non-goals is mandatory.** Scope exclusions cannot be inferred from omission. If authentication is out of scope, the PRD must say "DO NOT implement authentication" — not merely omit it [PLAN-14].
- **Machine-verifiable acceptance criteria only.** Acceptance criteria must replace all subjective language ("intuitive," "fast," "simple") with quantified thresholds and explicit behavioral conditions [PLAN-14].
- **Research mandates before implementation.** Agent training data lags platform evolution. PRDs must include a "research online for current API/SDK state" phase before implementation tasks, or agents will generate code against deprecated service versions [PLAN-14].
- **Explicit stability guards.** Sections of code or behavior that must remain unchanged need explicit `DO NOT CHANGE` directives. Agents optimized on large codebases will attempt "helpful" refactoring of stable patterns unless explicitly prohibited [PLAN-14].

**Epics and user stories restructured.** BMAD's framework produces the most detailed published prescription [PLAN-5][PLAN-16]: epics are now generated *after* architecture, because architectural decisions (database choice, API pattern, monorepo vs. polyrepo) directly constrain how work decomposes. The BMAD sequence is: market validation → PRD → architecture → epics → stories → tasks. Each story follows a three-tier structure: one-sentence objective, numbered requirements, checkbox acceptance criteria [PLAN-14]. Stories are kept small (5–15 minute agent work units) specifically to enable human checkpointing after each agent delivery [PLAN-14].

**Roadmaps at the factory level.** Roadmaps in a super-agile context shift from feature timelines to **spec quality milestones**. The bottleneck is no longer implementation velocity — "the bottleneck shifts from implementation speed to spec quality" [PLAN-4]. Roadmap planning must account for: spec authoring time (higher than equivalent ticket writing), scenario authoring time (a separate discipline), digital twin development for new external services, and LLM judge calibration for new scenario categories. A roadmap item is not "done" when code ships — it is done when satisfaction scores against the holdout scenario set exceed the threshold.

**AGENTS.md as the stable planning substrate.** The `AGENTS.md` file at the repository level now functions as a persistent planning contract: it encodes build commands, test commands, code style, security constraints, and commit conventions that apply to every agent session [PLAN-10]. Unlike PRDs and specs, which are per-feature, `AGENTS.md` is the standing operating procedure that persists across the roadmap. Teams should treat it as a first-class artifact maintained by a designated owner, versioned with change rationale.

**The BMAD role model.** BMAD's Agent-as-Code personas (Product Manager, Architect, Developer, Scrum Master, UX Designer) each defined as a Markdown file with responsibilities, constraints, and expected outputs [PLAN-16] — represent the organizational planning model. Rather than human-to-human handoffs between roles, handoffs are artifact-to-artifact: the PRD produced by the PM persona becomes the input to the Architect persona, and so forth. This makes the planning process auditable and reversible in ways that conversational agile planning is not.

**Trade-off: upfront rigor vs. agile adaptability.** The central tension is that spec-first planning looks like "waterfall" from the outside — detailed upfront specifications, sequential phase execution [PLAN-2]. Thoughtworks and others have flagged this risk: SDD can become a new form of big design up front if teams write complete specs for features that will change [PLAN-1]. The resolution is to scope specs to bounded, independently deployable capability units (not entire products), and to treat specs as living documents updated after each agent delivery cycle rather than frozen at project start [PLAN-6]. Contradicts [PLAN-4]: StrongDM's radical non-interactive model requires high spec completeness before any agent runs; this works for their domain (infrastructure security tooling with stable external API contracts) but may not generalize to product areas with rapidly shifting user requirements.

**Build recommendation.** A team standing up agent-driven planning should adopt this artifact hierarchy: `AGENTS.md` (standing operating contract) → `constitution.md`/steering files (organizational standards) → feature PRD with phase decomposition → per-phase spec files with six-element structure → scenario suite (separate repo, access-controlled). The planning cadence changes from sprint velocity to spec quality review: the bottleneck metric to track is "spec rejection rate" (how often an agent produces output that fails the scenario suite on first run), which is the leading indicator of spec quality and the most actionable feedback loop for the planning process.

---

## Summary

The shift from ticket-to-human to spec-to-agent delivery reorganizes the entire software planning stack around a single property: **precision as a forcing function**. Specs must be executable contracts, not communication devices — ambiguity that humans resolve through conversation becomes non-deterministic agent behavior. The six-element spec structure (outcomes, scope boundaries, constraints, prior decisions, task breakdown, verification criteria), the EARS notation formalized by Kiro, and the four-file layout popularized by GitHub Spec Kit all converge on the same requirement: every degree of freedom must be explicitly accounted for before the agent runs. The AGENTS.md open standard, now governed by the Linux Foundation's Agentic AI Foundation, provides the stable cross-platform substrate on which feature-level specs layer.

Scenario authoring as a holdout discipline is the quality control mechanism that makes non-interactive development trustworthy. StrongDM's adaptation of the ML holdout principle — keeping end-to-end user story scenarios invisible to the coding agent during development, then evaluating probabilistic satisfaction rather than binary pass/fail — is the most rigorous publicly documented approach. It requires treating scenario authoring as a distinct role (separate from spec writing, analogous to evaluation dataset design in ML) and investing in Digital Twin infrastructure for external service dependencies. Kaner's framework for scenario characteristics — realistic, complex, unambiguous outcome, motivating stakeholder, end-to-end — remains the correct quality bar for what constitutes a diagnostic scenario worth holding out.

Planning processes at the roadmap and epic level must restructure their output from communication documents to dependency-ordered, machine-verifiable artifacts. The BMAD method's sequence (market validation → PRD → architecture → epics → stories → tasks) delays epic decomposition until after architecture, producing higher-quality breakdown because architectural decisions constrain the work structure. The practical planning bottleneck in a super-agile factory is not implementation velocity but spec quality, measured by scenario satisfaction rates — which means the leading indicator teams should track on their roadmaps is spec rejection rate, not story points burned.

---

## References

[PLAN-1] Thoughtworks. "Spec-driven development: Unpacking one of 2025's key new AI-assisted engineering practices." *Thoughtworks Insights*. 2025. URL: https://www.thoughtworks.com/en-us/insights/blog/agile-engineering-practices/spec-driven-development-unpacking-2025-new-engineering-practices. Accessed: 2026-04-18.

[PLAN-2] Cloudstar, Alex. "Spec-Driven Development 2026: Future of AI Coding or Waterfall?" *alexcloudstar.com*. 2026. URL: https://www.alexcloudstar.com/blog/spec-driven-development-2026/. Accessed: 2026-04-18.

[PLAN-3] Willison, Simon. "How StrongDM's AI team build serious software without even looking at the code." *simonwillison.net*. 2026-02-07. URL: https://simonwillison.net/2026/Feb/7/software-factory/. Accessed: 2026-04-18.

[PLAN-4] Aktagon Signals. "Dark Factory Architecture: How Level 4 Actually Works." *signals.aktagon.com*. 2026-03. URL: https://signals.aktagon.com/articles/2026/03/dark-factory-architecture-how-level-4-actually-works/. Accessed: 2026-04-18.

[PLAN-5] Nayak, Plaban. "BMAD: AI-Powered Agile Framework Overview." *Medium*. 2026. URL: https://nayakpplaban.medium.com/bmad-ai-powered-agile-framework-overview-238d4af39aa4. Accessed: 2026-04-18.

[PLAN-6] Augment Code. "What Is Spec-Driven Development? A Practitioner's Guide for AI Coding." *augmentcode.com*. 2026. URL: https://www.augmentcode.com/guides/what-is-spec-driven-development. Accessed: 2026-04-18.

[PLAN-7] GitHub Blog. "Spec-driven development: Using Markdown as a programming language when building with AI." *github.blog*. 2025. URL: https://github.blog/ai-and-ml/generative-ai/spec-driven-development-using-markdown-as-a-programming-language-when-building-with-ai/. Accessed: 2026-04-18.

[PLAN-8] Amazon Web Services. "Introducing Kiro." *kiro.dev*. 2025. URL: https://kiro.dev/blog/introducing-kiro/. Accessed: 2026-04-18.

[PLAN-9] Microsoft Developer Blog. "Diving Into Spec-Driven Development With GitHub Spec Kit." *developer.microsoft.com*. 2025. URL: https://developer.microsoft.com/blog/spec-driven-development-spec-kit. Accessed: 2026-04-18.

[PLAN-10] Linux Foundation / agents.md. "AGENTS.md — An Open Standard for AI Coding Agents." *agents.md*. 2025. URL: https://agents.md/. Accessed: 2026-04-18.

[PLAN-11] Let's Data Science. "StrongDM Builds Software Factory With Agentic Testing." *letsdatascience.com*. 2026. URL: https://letsdatascience.com/news/strongdm-builds-software-factory-with-agentic-testing-c5aae799. Accessed: 2026-04-18.

[PLAN-12] Kaner, Cem. "An Introduction to Scenario Testing." *kaner.com (Florida Institute of Technology)*. 2003-06. URL: https://kaner.com/pdfs/ScenarioIntroVer4.pdf. Accessed: 2026-04-18.

[PLAN-13] Confident AI. "LLM Testing in 2026: Top Methods and Strategies." *confident-ai.com*. 2026. URL: https://www.confident-ai.com/blog/llm-testing-in-2024-top-methods-and-strategies. Accessed: 2026-04-18.

[PLAN-14] Haberlah, David. "How to write PRDs for AI Coding Agents." *Medium*. 2025. URL: https://medium.com/@haberlah/how-to-write-prds-for-ai-coding-agents-d60d72efb797. Accessed: 2026-04-18.

[PLAN-15] ChatPRD. "Writing PRDs for AI Code Generation Tools in 2026." *chatprd.ai*. 2026. URL: https://www.chatprd.ai/learn/prd-for-ai-codegen. Accessed: 2026-04-18.

[PLAN-16] Extinctsion. "BMAD: The Agile Framework That Makes AI Actually Predictable." *dev.to*. 2026. URL: https://dev.to/extinctsion/bmad-the-agile-framework-that-makes-ai-actually-predictable-5fe7. Accessed: 2026-04-18.
