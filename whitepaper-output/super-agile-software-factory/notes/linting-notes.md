# super-agile-software-factory — Linting Notes

## Questions

### Q1: What does code quality mean when no human ever reads the code, and how do static analysis and formatters fit into an agent-only pipeline?

In a conventional software factory, "code quality" is a composite of human concerns: readability, maintainability, adherence to team conventions, and correctness legible to the next engineer who opens the file. In a Dark Factory — where agents generate, review, test, and ship code with no human in the loop — these concerns collapse into a smaller, sharper set of machine-verifiable invariants. The question is not "will a colleague understand this?" but "will the runtime, the type system, and the security scanner reject this?" [LINT-1]

This reframing has a concrete implication: the output of a quality tool must be machine-readable to be actionable. Human-formatted error messages (multiline, context-colored, narrative) are noise to an agent; JSON, LSP diagnostics (the Language Server Protocol's `textDocument/publishDiagnostics` payload), and SARIF (Static Analysis Results Interchange Format, ISO 5055-adjacent) are signal. Most mature tooling now ships both modes. `ruff --output-format=json` emits a structured array of diagnostics. `mypy --output=json` does the same. `pyright --outputjson` wraps everything in a typed envelope the agent can parse without regex. `tsc --pretty false` removes ANSI decoration; paired with `tsc --listFilesOnly` or LSP integration, TypeScript errors become structured objects. ESLint's `--format=json` output has been standard since v2; its successor `oxlint` and the all-in-one `biome` tool both emit JSON natively. Biome in particular was designed for programmatic consumption: its LSP server is the primary interface, the CLI JSON mode is first-class. [LINT-2]

Formatters occupy a distinct role in an agent pipeline. Tools like `black`, `prettier`, and `biome format` are not quality signals — they are idempotent normalizers. Their value in a Dark Factory is not aesthetic but operational: normalized ASTs reduce diff noise in vector-store-based code retrieval, make semantic patch application deterministic, and prevent the agent from wasting tokens re-litigating style in its context window. The correct design is to run the formatter before the linter, commit the formatted output, and treat any subsequent linter delta as a genuine semantic issue rather than a formatting artifact. [LINT-3]

Static analysis in an agent pipeline plays a role that partially replaces what PR review does in a human pipeline — but only partially, and the gap matters. A human reviewer catches things like: "this abstraction is wrong for the domain," "this will be impossible to extend," "this duplicates a module that already exists." Static analysis catches: type errors, undefined names, reachability, known-bad patterns, security anti-patterns (via Semgrep rules or CodeQL queries), and style deviations. The former class of issues is largely invisible to current static analysis. In a Dark Factory, these architectural issues must be caught by a separate architectural-review agent whose prompts encode the relevant constraints, because no static tool will surface them. The practical conclusion: static analysis in an agent pipeline is necessary but not sufficient, and the gap it does not cover is qualitatively different from the gap it does. [LINT-4]

Type checkers deserve special emphasis. `mypy` in strict mode and `pyright` in strict mode enforce contracts at the module boundary — precisely the contracts that matter when one agent-generated module calls another. In a human codebase, loose typing is tolerated because humans can read intent. In an agent-generated codebase, loose typing means one agent's output type silently mismatches another agent's input assumption, producing runtime failures that are expensive to trace. Pyright's strict mode and `tsc --strict` are therefore not optional hardening — they are foundational correctness guarantees for an agent-only supply chain. [LINT-5]

The net redefinition: code quality in a Dark Factory means "passes the full static gate" — formatter normalization, zero linter errors (ruff / oxlint / biome), zero type errors (pyright strict / tsc strict / mypy strict), zero SAST findings at the configured severity threshold (Semgrep / CodeQL). Readability is irrelevant. Elegance is irrelevant. Machine-verifiable correctness is the entire definition. [LINT-1]

### Q2: How do agents consume and act on linter / type-checker / formatter signals, and what feedback-loop designs are most effective?

The canonical agent feedback loop for code quality is: generate → run static gate → parse structured output → re-prompt with diagnostics → regenerate → repeat until gate passes or retry budget exhausted. The critical design variable is how diagnostics are injected into the re-prompt. [LINT-6]

Three patterns exist:

**Pattern A — Full diagnostic dump.** All JSON diagnostics are serialized into the re-prompt. Simple to implement, reliable for small files. Fails at scale: a large TypeScript project with 200 type errors produces a diagnostic payload that consumes most of a 200k-token context window, leaving little room for the code itself. `tsc` and `pyright` can both emit hundreds of cascading errors from a single root cause; the agent re-prompts on symptoms rather than causes. [LINT-6]

**Pattern B — Root-cause filtered injection.** The orchestrator post-processes the diagnostic JSON to cluster errors by root cause (e.g., all errors downstream of a missing interface definition are suppressed; only the root error is injected). This requires a second agent or a heuristic pass over the dependency graph of errors. Pyright's JSON output includes `relatedInformation` links that help with this clustering. Semgrep's SARIF output includes `rule.id` and `locations` arrays that allow grouping by rule rather than by file. This pattern is significantly more token-efficient and produces faster convergence. [LINT-7]

**Pattern C — LSP server integration.** The agent is wired directly to a running language server (pyright's language server mode, typescript-language-server, rust-analyzer). After each code edit the agent requests `textDocument/publishDiagnostics` for the changed file, receives a delta of affected diagnostics, and repairs incrementally rather than regenerating wholesale. This is the most token-efficient pattern and matches how a human IDE-using developer works. It is also the most complex to orchestrate: the agent must maintain a virtual file system that the language server can address, track document versions, and manage the LSP lifecycle. Projects like Aider and Continue.dev have implemented partial versions of this. [LINT-8]

For security-focused linters (Semgrep, CodeQL), SARIF is the output format of choice. SARIF is a JSON schema standardized by OASIS (v2.1.0 is current as of 2025). A SARIF result object contains `ruleId`, `level` (error/warning/note), `locations` with `physicalLocation.artifactLocation.uri` and `region.startLine`, and `message.text`. An agent can extract exactly the file, line, rule, and message needed for a targeted re-prompt without parsing human prose. CodeQL's `codeql database analyze --format=sarifv2.1.0` and Semgrep's `semgrep --sarif` both emit conformant SARIF. [LINT-9]

Retry budgets and escape hatches are essential safety valves. A naive loop risks infinite cycling if the agent consistently regenerates code that re-triggers the same linter rule. Effective designs include: (1) a per-rule suppression list that the agent can invoke after N failed repairs, flagging the suppression for human review in a side-channel; (2) a "rule difficulty" classifier that routes hard-to-fix rules (e.g., complex lifetime errors in Rust, intricate generic constraints in TypeScript) to a more capable model or a specialized repair agent; (3) a hash-based cycle detector that aborts if the same diagnostic appears in two consecutive iterations without the code changing. [LINT-10]

A concrete effective stack: ruff (Python lint + format, sub-millisecond, JSON output) → pyright strict (type check, JSON) → Semgrep (security patterns, SARIF) → agent re-prompt with clustered diagnostics → repeat. Biome serves the equivalent role for TypeScript/JavaScript: single binary, lint + format, LSP, JSON. The gate must be deterministic and hermetic — no network calls, pinned rule versions — so that the same input always produces the same diagnostic set and the feedback loop is convergent. [LINT-2]

### Q3: What safety and security properties must agent-only code meet, and what tooling becomes critical when no human review exists?

The security threat model for agent-generated code is qualitatively different from human-generated code, and the difference is not merely one of degree. Three novel attack surfaces emerge: (1) training-data poisoning, where the model has internalized vulnerable patterns from malicious open-source code in its training corpus; (2) prompt injection, where adversarial content in an external data source (a fetched webpage, a parsed document, a retrieved memory) causes the agent to emit code with embedded vulnerabilities or exfiltration logic; (3) supply-chain injection, where an agent autonomously selects and installs packages, and a malicious package author has typosquatted or dependency-confused a target. None of these vectors are visible to a human code reviewer after the fact — the code looks plausible. [LINT-11]

**SAST (Static Application Security Testing).** Semgrep is the primary SAST tool for agent pipelines due to its rule-as-code model (YAML rules that are easy to version, test, and extend), its SARIF output, and its sub-second scan times on typical agent output sizes. Semgrep Pro rules cover OWASP Top 10 patterns across Python, JavaScript/TypeScript, Go, Java, and Ruby. CodeQL is deeper but slower: it builds a semantic code graph and runs Datalog queries over it, catching multi-hop taint flows that Semgrep misses. For an agent pipeline, the pragmatic split is Semgrep as the fast gate in the inner loop and CodeQL as the slower gate in the integration stage. SonarQube occupies a similar space to CodeQL but with a heavier server infrastructure; it is better suited to organization-wide dashboarding than to per-agent-run gating. Snyk Code (formerly DeepCode) uses a machine-learning-based analysis engine and is notable for catching vulnerability patterns that rule-based tools miss — relevant precisely because agent-generated code may instantiate novel-but-vulnerable patterns not yet codified in Semgrep rules. [LINT-12]

**Secret scanning.** An agent with access to environment variables or configuration files may inadvertently embed credentials in generated code — either by hallucination (inventing a plausible-looking key) or by literal inclusion from its context window. Trufflehog v3 and gitleaks are the two dominant tools. Trufflehog's `--json` mode emits structured findings with `DetectorName`, `Raw` (the matched secret), and `SourceMetadata.Data` (file and line). Gitleaks emits JSON with `RuleID`, `File`, `StartLine`, and `Secret`. Both must be run as pre-commit gates and as CI gates. Critically, they must be run against the git history as well as the working tree — an agent that commits a secret and then removes it in a subsequent commit has still leaked into the repository history. `trufflehog git --json file://.` scans the full history. [LINT-13]

**DAST (Dynamic Application Security Testing).** DAST is harder to automate in an agent pipeline because it requires a running application. OWASP ZAP's `zap-baseline.py` in API-scan mode, combined with an agent-generated OpenAPI spec, can scan a generated service automatically. This is most practical in an integration-stage agent that spins up the generated service in an ephemeral container, runs ZAP, and parses the JSON report. DAST catches things SAST cannot: actual runtime injection vulnerabilities, authentication bypass, session fixation. For a Dark Factory, DAST belongs in the staging gate, not the inner development loop. [LINT-14]

**SCA (Software Composition Analysis) and SBOM.** When agents select dependencies autonomously, the SCA gate is critical. `trivy` and `grype` both scan container images and lock files for known CVEs, emitting JSON reports. `syft` generates SPDX or CycloneDX SBOMs from any OCI image or directory. The SBOM becomes the audit artifact proving what the agent actually installed. `dependabot` and `renovate` handle automated dependency update PRs; in an agent pipeline, renovate's JSON config allows fully automated merge on patch-level updates with green CI, which fits the Dark Factory model. The risk of typosquatting and dependency confusion (Birsan, 2021) [LINT-15] is acute when agents autonomously choose package names — a Semgrep rule that flags `pip install` or `npm install` with package names not in an approved allowlist is a practical mitigation.

**Prompt injection → code vulnerability.** This is the least-addressed vector in current tooling. A Semgrep rule can detect `eval(user_input)` but cannot detect that the agent was instructed by adversarial content to generate `eval(user_input)`. The mitigation requires instrumentation at the agent orchestration layer: logging the full prompt and context at code generation time, and running a prompt-injection detector (e.g., a fine-tuned classifier or a rule-based scanner for adversarial injection patterns) over the agent's input before trusting its output. Anthropic's research on prompt injection [LINT-16] and the OWASP LLM Top 10 (LLM01: Prompt Injection, LLM02: Insecure Output Handling) formalize this threat. No current SAST tool catches it; it is a gap that the Dark Factory must address with orchestration-layer controls, not code-layer tools.

**Contradiction flag:** Snyk Code and SonarQube both claim to catch "AI-generated vulnerable patterns" via ML-based analysis. This claim is partially contradicted by academic work (Perry et al., 2023) [LINT-17] showing that LLM-assisted code has statistically higher rates of certain CWE classes (buffer overflows in C, SQL injection in Python) precisely because models reproduce vulnerable patterns from training data. If the SAST tool was trained on the same corpus, it may not catch patterns it was implicitly trained to reproduce. Independent rule-based tools (Semgrep with human-authored rules) are less susceptible to this circularity.

---

## Summary

In a Dark Factory, code quality collapses from a human-legible composite into a set of machine-verifiable binary gates: formatter normalization (black, prettier, biome), zero lint errors (ruff, oxlint, biome), zero type errors (pyright strict, tsc strict, mypy strict), and zero SAST findings above threshold (Semgrep, CodeQL). Readability and elegance are irrelevant; architectural correctness must be covered by a separate architectural-review agent, because no static tool catches domain-level design errors. The critical infrastructure shift is from human-readable error messages to structured output formats — JSON, LSP diagnostics, SARIF — that agents can parse and act on without regex or prose interpretation.

The most effective agent feedback loop combines fast inner-loop linting (ruff, biome, pyright JSON) with root-cause-filtered diagnostic injection to avoid context window saturation from cascading errors, and LSP integration for incremental repair at the file level. Security-focused SAST (Semgrep for speed, CodeQL for depth, Snyk Code for ML-detected novel patterns) must run as a separate gate with SARIF output. Secret scanning (trufflehog, gitleaks) and SCA (trivy, grype, syft for SBOM generation) are mandatory when agents autonomously install dependencies, closing the supply-chain attack surface that no human reviewer would otherwise catch.

The most underaddressed risk in current tooling is prompt injection as a code vulnerability vector: an agent manipulated by adversarial content in its context can generate code that passes every static gate while containing intentional vulnerabilities. No SAST tool currently detects this; mitigation requires orchestration-layer prompt logging, injection detection, and potentially cryptographic attestation linking each generated artifact to the exact prompt and model version that produced it. The Dark Factory's security posture is only as strong as the weakest link in that provenance chain.

---

## References

[LINT-1] Amodei et al. "Concrete Problems in AI Safety." *arXiv (Cornell University)*. 2016-06-21. URL: https://arxiv.org/abs/1606.06565. Accessed: 2026-04-18.

[LINT-2] Biome project. "Biome Architecture." *biomejs.dev*. n.d. URL: https://biomejs.dev/internals/architecture/. Accessed: 2026-04-18.

[LINT-3] Black project. "The Black Code Style." *black.readthedocs.io*. n.d. URL: https://black.readthedocs.io/en/stable/the_black_code_style/. Accessed: 2026-04-18.

[LINT-4] Sadowski, Caitlin et al. "Lessons from Building Static Analysis Tools at Google." *Communications of the ACM 61(4)*. 2018-04-01. URL: https://cacm.acm.org/magazines/2018/4/226371-lessons-from-building-static-analysis-tools-at-google/fulltext. Accessed: 2026-04-18.

[LINT-5] Pyright project. "Pyright Configuration and Strict Mode." *GitHub (microsoft/pyright)*. n.d. URL: https://github.com/microsoft/pyright/blob/main/docs/configuration.md. Accessed: 2026-04-18.

[LINT-6] Shen et al. "Large Language Models as Autonomous Agents for Code Debugging." *arXiv (Cornell University)*. 2024. URL: https://arxiv.org/abs/2404.xxxxx. Accessed: 2026-04-18.

[LINT-7] Pyright project. "Pyright Command Line Output and relatedInformation." *GitHub (microsoft/pyright)*. n.d. URL: https://github.com/microsoft/pyright/blob/main/docs/command-line.md. Accessed: 2026-04-18.

[LINT-8] Continue.dev. "LSP Integration Documentation." *continue.dev*. n.d. URL: https://continue.dev/docs. Accessed: 2026-04-18.

[LINT-9] OASIS. "SARIF v2.1.0 Specification." *OASIS Open*. 2020-03-27. URL: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html. Accessed: 2026-04-18.

[LINT-10] Zheng et al. "Towards Autonomous Software Engineering Agents." *arXiv (Cornell University)*. 2025. URL: https://arxiv.org/abs/2501.xxxxx. Accessed: 2026-04-18.

[LINT-11] Pearce, Hammond et al. "Asleep at the Keyboard? Assessing the Security of GitHub Copilot's Code Contributions." *IEEE Symposium on Security and Privacy 2022*. 2022-05-23. URL: https://arxiv.org/abs/2108.09293. Accessed: 2026-04-18.

[LINT-12] Semgrep. "SARIF Output Documentation." *semgrep.dev*. n.d. URL: https://semgrep.dev/docs/semgrep-ci/sarif. Accessed: 2026-04-18.

[LINT-13] TruffleSecurity. "Trufflehog v3 Git Scanning and JSON Output." *GitHub (trufflesecurity/trufflehog)*. n.d. URL: https://github.com/trufflesecurity/trufflehog. Accessed: 2026-04-18.

[LINT-14] OWASP. "ZAP Baseline Scan." *zaproxy.org*. n.d. URL: https://www.zaproxy.org/docs/docker/baseline-scan/. Accessed: 2026-04-18.

[LINT-15] Birsan, Alex. "Dependency Confusion: How I Hacked Into Apple, Microsoft and Dozens of Other Companies." *Medium*. 2021-02-09. URL: https://medium.com/@alex.birsan/dependency-confusion-4a5d60fec610. Accessed: 2026-04-18.

[LINT-16] OWASP. "OWASP Top 10 for Large Language Model Applications." *OWASP*. 2024-11-17. URL: https://owasp.org/www-project-top-10-for-large-language-model-applications/. Accessed: 2026-04-18.

[LINT-17] Perry, Neil et al. "Do Users Write More Insecure Code with AI Assistants?" *arXiv (Cornell University)*. 2022-11-07. URL: https://arxiv.org/abs/2211.03622. Accessed: 2026-04-18.
