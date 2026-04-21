## Q2 Notes

### The October 2024 Inflection: Sonnet 3.5 v2 and the Compounding Correctness Threshold

The first technical inflection enabling the Software Factory paradigm arrived in October 2024 with the release of Claude 3.5 Sonnet v2 (claude-3-5-sonnet-20241022). Anthropic's model card addendum documented a step-change in agentic coding performance: SWE-bench Verified jumped from 33.4% (original 3.5 Sonnet) to 49.0%, alongside TAU-bench retail-domain tool-use climbing from 62.6% to 69.2% [Q2-1]. The more consequential shift was qualitative: as StrongDM's Jay Taylor, Navan Chauhan, and Justin McCarthy later articulated, "with the second revision of Claude 3.5 (October 2024), long-horizon agentic coding workflows began to compound correctness rather than error" [Q2-2].

"Compounding correctness vs. accumulating error" describes a phase transition in closed-loop agent behavior. In pre-threshold models, each agent step in a long-horizon loop introduced a small probability of semantic drift, tool-call hallucination, or context corruption; these errors compounded geometrically, making tasks beyond ~10 steps unreliable. Post-threshold, the validation feedback signal became strong enough that the loop *converged*: errors detected by harness runs triggered corrective re-generation, and the net trajectory bent toward correctness rather than away from it. The loop architecture — seed spec → code generation → scenario harness → LLM-evaluated diff → next iteration — only works as an autonomous factory when each iteration's error rate is below the correction rate. The October 2024 Sonnet delivered that sub-threshold error profile for the first time at scale [Q2-2].

Cursor's YOLO mode (shipped in version 0.44, December 2024) served as a publicly legible market signal of this inflection. YOLO mode enabled the Composer agent to auto-run terminal commands, check exit codes, install dependencies, and iterate on failures in sequence — precisely the closed-loop topology that Software Factory thinking requires — without requiring per-command human confirmation [Q2-3]. Its rapid uptake and positive reception in the practitioner community confirmed that the model reliability bar had crossed a threshold where human-in-the-loop approval at each tool call was no longer necessary for routine development flows.

### The November 2025 Inflection: Opus 4.5 and GPT-5.2 Turn the Reliability Corner

The second and sharper inflection arrived in November 2025. Anthropic shipped Claude Opus 4.5 on November 24, 2025, delivering what its release page characterized as "the best model in the world for coding, agents, and computer use" [Q2-4]. On SWE-bench Verified it scored 80.9%, the highest of any publicly benchmarked model at that time, with a 10.6% gain over Sonnet 4.5 on Aider Polyglot and a 29% improvement on Vending-Bench (specifically designed to measure *long-haul consistency* across extended agentic sessions) [Q2-4]. Critically, Opus 4.5 achieved equivalent or superior benchmark scores using substantially fewer output tokens than Sonnet 4.5 — matching Sonnet's best scores with 76% fewer output tokens at medium effort — a signal of improved instruction-following density rather than brute-force token scaling [Q2-4].

OpenAI's GPT-5.2, released in December 2025, contributed a complementary capability profile. Simon Willison's post on the StrongDM factory approach summarizes the combined inflection: "Claude Opus 4.5 and GPT 5.2 appeared to turn the corner on how reliably a coding agent could follow instructions" [Q2-2]. The qualitative difference from the October 2024 inflection is *instruction-following fidelity under compositional complexity*: earlier models could reliably execute a single NLSpec directive; the November 2025 wave could sustain fidelity across multi-spec pipelines where attractor-spec.md, coding-agent-loop-spec.md, and unified-llm-spec.md are composed simultaneously.

### StrongDM's Two Public Artifacts

**Attractor** (`github.com/strongdm/attractor`, created 2026-02-05) is a pure NLSpec repository — no executable source code exists in it [Q2-5]. A full recursive tree confirms exactly five files: `LICENSE`, `README.md`, `attractor-spec.md` (93 KB), `coding-agent-loop-spec.md` (72 KB), and `unified-llm-spec.md` (113 KB). The README instructs practitioners to point a coding agent (Claude Code, Codex, Cursor) at the URL and issue: "Implement Attractor as described by https://github.com/strongdm/attractor." The repo thus dogfoods its own thesis: a Dark Factory product whose artifact is the spec, not the source [Q2-6]. The three spec files collectively define (1) the declarative DOT-syntax pipeline graph, (2) the agent loop with retry, checkpoint, and goal-gate logic, and (3) a unified multi-provider LLM client. Attractor is to the Software Factory what a hardware architecture manual is to a chip: the normative description from which implementations are synthesized.

**cxdb** (`github.com/strongdm/cxdb`, created 2026-01-30) is the "AI Context Store" — durable, branch-friendly storage of conversation histories and tool outputs [Q2-7]. The fundamental abstraction is an immutable Turn DAG backed by a content-addressed blob store (BLAKE3 hashing). Branching is O(1): creating a new head pointer that references an existing turn, with no history copy. The server exposes a binary protocol on port 9009 (length-prefixed msgpack frames) and an HTTP/JSON gateway on port 9010. Willison's post cited the codebase at release as approximately 16k lines of Rust, 9.5k Go, and 6.7k TypeScript [Q2-2]. Language byte counts have since grown substantially (Rust: 903 KB, TypeScript: 524 KB, Go: 320 KB), consistent with continued active development [Q2-8].

**factory.strongdm.ai** provides a third public artifact layer: the Techniques page documents six named patterns — Gene Transfusion, Semports, Pyramid Summaries, Shift Work, Digital Twin Universe, The Filesystem [Q2-9]. The framework treats generated code as opaque artifacts — "like ML model weights" — validated exclusively through externally observable behavior, never by human inspection of source.

## Q2 References

[Q2-1] Anthropic. "Model Card Addendum: Claude 3.5 Haiku and Upgraded Claude 3.5 Sonnet." *Anthropic*. 2024-10-22. URL: https://www.anthropic.com/news/3-5-models-and-computer-use. Accessed: 2026-04-18.

[Q2-2] Willison, Simon. "How StrongDM's AI team build serious software without even looking at the code." *simonwillison.net*. 2026-02-07. URL: https://simonwillison.net/2026/Feb/7/software-factory/. Accessed: 2026-04-18.

[Q2-3] Cursor. "Changelog 0.44.x — Agent YOLO mode." *cursor.com*. 2024-12. URL: https://cursor.com/changelog/0-44-x. Accessed: 2026-04-18.

[Q2-4] Anthropic. "Introducing Claude Opus 4.5." *anthropic.com*. 2025-11-24. URL: https://www.anthropic.com/news/claude-opus-4-5. Accessed: 2026-04-18.

[Q2-5] GitHub. "strongdm/attractor." *GitHub (strongdm/attractor)*. 2026-02-05. URL: https://github.com/strongdm/attractor. Accessed: 2026-04-18.

[Q2-6] strongdm. "attractor/README.md." *GitHub (strongdm/attractor)*. 2026-02-05. URL: https://github.com/strongdm/attractor/blob/main/README.md. Accessed: 2026-04-18.

[Q2-7] GitHub. "strongdm/cxdb — AI Context Store for agents and LLMs." *GitHub (strongdm/cxdb)*. 2026-01-30. URL: https://github.com/strongdm/cxdb. Accessed: 2026-04-18.

[Q2-8] GitHub. "strongdm/cxdb — Language statistics." *GitHub (strongdm/cxdb)*. 2026-04-18. URL: https://github.com/strongdm/cxdb. Accessed: 2026-04-18.

[Q2-9] StrongDM. "Techniques." *factory.strongdm.ai*. 2026. URL: https://factory.strongdm.ai/techniques. Accessed: 2026-04-18.

## Q2 Summary

Two model-generation inflection points bracket the Software Factory paradigm's viability window: the October 2024 Claude 3.5 Sonnet v2 release, which crossed the threshold where long-horizon agentic loops compound correctness rather than accumulate error (confirmed publicly by Cursor's YOLO mode adoption in December 2024), and the November–December 2025 wave of Claude Opus 4.5 and GPT-5.2, which extended that reliability to complex multi-spec compositional instruction-following at production scale. StrongDM's two concrete public artifacts — the attractor NLSpec repo (pure Markdown, zero source code, verified) and cxdb (immutable DAG context store, grown from ~32k LOC at Willison's February 2026 post to an estimated ~41k LOC by April 2026) — together operationalize the paradigm: the first provides the normative implementation target synthesizable by any compliant coding agent, the second provides the durable context infrastructure that makes stateful, branch-safe agentic collaboration tractable at factory scale.
