# super-agile-software-factory — Research Questions

<!-- Research questions for the super-agile-software-factory topic. -->

## General Understanding

### Q1: What is the StrongDM "Software Factory" / Dan Shapiro "Dark Factory" paradigm, and what is its primary operating-model claim?

**Search terms:**
- StrongDM software factory agentic coding
- Dan Shapiro five levels dark factory
- Simon Willison software factory February 2026

### Q2: Which technical inflection points made this paradigm viable, and what concrete artifacts has StrongDM released to demonstrate it?

**Search terms:**
- Claude Opus 4.5 GPT-5.2 November 2025 inflection agentic coding
- strongdm attractor github spec-only repo
- strongdm cxdb immutable DAG context store

### Q3: How does the "no human reviews code" posture differ from existing agent-coding practice (Cursor YOLO, AIDER, Devin, SWE-agent), and what does it imply for the future of software engineering?

**Search terms:**
- Cursor YOLO mode long-horizon coding
- autonomous coding agents state of the art 2026
- software engineering workflow agent replace human reviewer

### Q4: What primary-source evidence exists for the Software Factory's three-legged verification stool — scenarios, satisfaction, digital twin universe — and how are each of these implemented in practice?

**Search terms:**
- scenario testing Cem Kaner holdout software factory
- satisfaction metric LLM-as-judge trajectory evaluation
- digital twin universe SaaS API clone agent

---

## Deeper Dive

### Subtopic 1: Planning

#### Q1: How are specifications structured when they replace source code as the primary human artifact, and what conventions govern spec-driven agentic development?

**Search terms:**
- spec-driven development markdown coding agent
- executable specifications software factory attractor
- machine-readable spec format agent coding

#### Q2: How is scenario authoring practiced as an ML-holdout discipline, and what makes a good end-to-end scenario for a super-agile factory?

**Search terms:**
- scenario testing ML holdout software quality
- Cem Kaner scenario testing book
- end-to-end user story LLM grader

#### Q3: What planning processes and artifacts (roadmaps, epics, PRDs) need to change when the unit of delivery is a spec handed to an agent rather than a ticket handed to a human?

**Search terms:**
- PRD agent-friendly super-agile planning
- replacing epics with specs AI coding
- roadmap planning agent-driven development

---

### Subtopic 2: Architecture

#### Q1: What system components make up a super-agile factory end-to-end, and how do the agent harness, context store, scenario bank, DTU, and satisfaction evaluator interact?

**Search terms:**
- agent harness architecture coding agent
- cxdb immutable DAG AI context store
- digital twin universe architecture software factory

#### Q2: What are real-world build-vs-buy options for each architectural component (agent runtimes, spec stores, DTU clones, evaluators), and which are commodity vs differentiated?

**Search terms:**
- LangGraph Claude Agent SDK harness build or buy
- agent context store comparison 2026
- LLM as judge evaluator commercial vs DIY

#### Q3: How do immutable DAG context stores differ from conversation logs / RAG, and why does this matter for agent determinism and replayability?

**Search terms:**
- immutable DAG agent conversation store
- replayability LLM agent deterministic
- cxdb design rationale

---

### Subtopic 3: Coding

#### Q1: What makes a long-horizon coding loop compound correctness rather than accumulate error, and what harness-level design choices enable this?

**Search terms:**
- long-horizon agentic coding reliability
- compound correctness coding agent loop
- self-correction LLM agent error recovery

#### Q2: What are the supporting techniques — Gene Transfusion, Semports, Pyramid Summaries — as described by StrongDM, and how do they generalize to any factory?

**Search terms:**
- StrongDM gene transfusion technique
- StrongDM semport cross-language port
- pyramid summaries agent context compression

#### Q3: What is the non-interactive coding agent pattern (Attractor-style) and how does it differ from interactive CLI agents like Claude Code, Aider, and Cursor's agent mode?

**Search terms:**
- non-interactive coding agent Attractor StrongDM
- autonomous coding agent vs interactive
- headless coding agent CI pipeline

---

### Subtopic 4: Linting and Code Quality

#### Q1: What does code quality mean when no human ever reads the code, and how do static analysis and formatters fit into an agent-only pipeline?

**Search terms:**
- static analysis AI generated code quality
- machine-readable quality signal coding agent
- linter role autonomous code generation

#### Q2: How do agents consume and act on linter / type-checker / formatter signals, and what feedback-loop designs are most effective?

**Search terms:**
- agent feedback loop linter error
- LLM coding agent type checker fix
- autonomous code quality repair loop

#### Q3: What safety and security properties must agent-only code meet, and what tooling (SAST, DAST, SBOM, secret scanning) becomes critical when no human review exists?

**Search terms:**
- SAST coding agent autonomous
- security review agent-generated code
- secret scanning AI generated code

---

### Subtopic 5: Testing

#### Q1: How does probabilistic trajectory-level satisfaction replace green/red test verdicts, and what are the anti-cheating properties required?

**Search terms:**
- LLM as judge trajectory evaluation
- satisfaction metric probabilistic software test
- holdout set testing coding agent

#### Q2: How are Digital Twin Universe clones built in practice, and what fidelity strategies (SDK-client-compatibility, top-SDK pinning) work?

**Search terms:**
- SaaS API clone fidelity SDK compatibility
- simulate third-party API for testing
- digital twin Okta Jira Slack agent-built

#### Q3: At what volume and diversity do scenario runs become a meaningful verification signal, and what are the compute/time budgets?

**Search terms:**
- scenario testing at scale LLM
- volume testing agent trajectories
- test budget compute coding agent

---

### Subtopic 6: Deployment and Operations

#### Q1: What does CI/CD look like for agent-authored code when no human reviews the diff, and what canary/rollback strategies apply?

**Search terms:**
- CI/CD agent-authored code canary
- progressive rollout autonomous code deployment
- rollback strategy AI generated software

#### Q2: What observability surfaces matter for agent trajectories in production (LangSmith, Langfuse, Phoenix, OpenTelemetry-GenAI), and how do they differ from conventional APM?

**Search terms:**
- LangSmith agent observability production
- Langfuse trajectory telemetry
- OpenTelemetry GenAI semantic conventions 2026

#### Q3: How do you govern deploys at volume when features ship in days/weeks — change-management, audit, compliance when humans never read code?

**Search terms:**
- compliance AI generated code audit
- SOC2 agent authored code
- change management no human review software

---

### Subtopic 7: Economics and Team Shape

#### Q1: What is the actual token economics of a super-agile factory (cost/day/engineer), what ROI justifies it, and how does the math break down at different scales?

**Search terms:**
- token cost agentic coding engineer month
- Claude Opus budget coding agent ROI
- LLM software development economics 2026

#### Q2: What team shapes and roles does the paradigm reward (small elite teams, shift from author to reviewer of specs), and what happens to middle-management and PR-review culture?

**Search terms:**
- small AI coding team staffing 2026
- role of engineer AI coding agent 2026
- elite team agent coding shipping velocity

#### Q3: What competitive dynamics arise when features can be cloned in hours of agent work (IP decay, moat erosion, dev-velocity arms race)?

**Search terms:**
- competitive moat AI code generation
- feature clone agent coding commoditization
- software IP decay AI 2026

---

### Subtopic 8: Risks and Open Problems

#### Q1: What kinds of software and domains break the super-agile paradigm (novel problems without existing patterns, missing APIs, ambiguous specs, safety-critical)?

**Search terms:**
- limits autonomous coding agent novel domain
- safety critical AI generated code 2026
- where agent coding fails research

#### Q2: What are the model/provider lock-in risks, and how do teams hedge against regression, price changes, or deprecation?

**Search terms:**
- model lock-in agentic coding multi-provider
- Claude OpenAI coding agent portability
- model deprecation agent workflow

#### Q3: What are the unresolved scientific and engineering problems — test-cheating, reward hacking, spec-ambiguity, prompt-injection across agent chains?

**Search terms:**
- reward hacking coding agent
- prompt injection multi-agent chain
- spec ambiguity LLM implementation 2026

---

## Redundant Questions

<!-- Move any redundant questions here during review. -->
