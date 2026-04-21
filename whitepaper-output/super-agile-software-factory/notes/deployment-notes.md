# super-agile-software-factory — Deployment Notes

## Questions

### Q1: What does CI/CD look like for agent-authored code when no human reviews the diff, and what canary/rollback strategies apply?

In a super-agile software factory, the CI/CD pipeline becomes the last line of defense that humans actually designed — and then mostly stepped away from. The canonical shape looks like this: an agent commits to a feature branch, a GitHub Actions or GitLab CI pipeline triggers immediately, runs a static analysis gauntlet (SAST, dependency scanning, license checks, secret detection), executes the full test suite including agent-generated tests, and — if green — merges automatically to a staging integration branch. No human reads the diff. This is not hypothetical; teams at hyperscalers have been running variants of this since 2024, and the pattern has solidified around a few key conventions [DEPLOY-1].

The artifact promotion path typically flows: build → unit/integration tests → container image signing (Sigstore/cosign) → SBOM generation → push to registry → Argo CD or Flux picks up the new image tag and begins a canary rollout. Spinnaker remains popular in larger organizations that need cross-cloud orchestration, though its operational overhead has pushed many teams toward Argo Rollouts, which integrates natively with Kubernetes and expresses canary strategy as a CRD [DEPLOY-2].

**Canary signals when no human has read the diff** are the critical design question. Since you cannot rely on a reviewer saying "this looks risky," the pipeline must be instrumented to detect regression signals automatically. The practical set of rollback triggers includes: (1) error-rate increase beyond a baseline threshold (typically p99 latency or 4xx/5xx rate measured against the previous 24-hour window), (2) custom business-metric degradation — conversion rate, order throughput, whatever the service owns — gated via LaunchDarkly or Statsig experimentation layers that compare canary versus stable cohorts, (3) model behavior drift for agent-facing services, measured as embedding distance or output distribution shift, surfaced through Arize Phoenix or W&B Weave sidecar evaluation runs, and (4) security signals: if a runtime policy engine (Falco, OPA Gatekeeper) fires on the canary pod, the rollout halts immediately [DEPLOY-3].

Rollback itself is mechanical: Argo Rollouts or Flux will revert to the last known-good image tag within seconds. The subtler problem is *blast radius scoping*. Progressive delivery frameworks like Flagger support traffic splitting at 1% / 5% / 20% / 50% / 100% with automated promotion gates between each step. For agent-authored code, teams are adding an extra gate: a lightweight "shadow eval" step where the canary handles a small percentage of production traffic but its responses are also evaluated by a secondary judge-agent against a golden dataset before promotion past 5% [DEPLOY-4].

Feature flags via LaunchDarkly, Statsig, or Unleash decouple deployment from release at the application layer, which is especially valuable when agent outputs are probabilistic. You can deploy the binary to 100% of hosts but expose the feature to 0.1% of users, observe behavior, and expand — or kill — without a new deploy cycle. Unleash's open-source SDK is popular in regulated industries where SaaS flag services create data-residency concerns [DEPLOY-5].

**Contradiction to flag:** Some canary frameworks assume human judgment as a final promotion gate ("soak period + human approves"). In a no-review pipeline, this gate either disappears or is replaced by an automated judge. The risk is that automated judges can be fooled by the same adversarial inputs that fooled the generating agent — the eval loop is not independent if both the generator and evaluator share the same base model family [DEPLOY-6].

### Q2: What observability surfaces matter for agent trajectories in production, and how do they differ from conventional APM?

Conventional APM (Datadog, New Relic, Dynatrace) was designed around deterministic call graphs: a request enters, traverses a known set of functions, exits. Latency and error rate are sufficient signals because the same input reliably produces the same output. Agent trajectories break every one of these assumptions [DEPLOY-7].

An agent trajectory is a DAG of tool calls, LLM completions, memory reads, and sub-agent invocations whose shape is determined at runtime. The same user request can produce a two-hop trajectory on one invocation and a twelve-hop trajectory with a loop and a retry on another. This means spans are necessary but not sufficient — you need *semantic* span attributes that capture the agent's reasoning state, not just execution timing.

**OpenTelemetry GenAI semantic conventions (2026 revision)** define the standard attribute namespace for this. Key attributes include `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reason`, and — critically — `gen_ai.agent.name` and `gen_ai.agent.tool_calls` for multi-agent traces. The 2026 conventions also introduced `gen_ai.trajectory.step_index` to order steps within a multi-turn session, enabling reconstruction of the full trajectory from a flat span list [DEPLOY-8].

**LangSmith** (LangChain's hosted platform) captures full LLM traces natively for LangChain/LangGraph workloads. Its production differentiator is online evaluation: you can attach evaluator functions that score every production trace against criteria (faithfulness, tool call validity, output schema conformance) in near-real time, with results surfaced as metrics alongside latency. Feedback loops from human raters can be added without changing agent code [DEPLOY-9].

**Langfuse** is the open-source alternative with comparable trace capture, a prompt management layer, and a cost ledger per trace. Its 2025/2026 trajectory: self-hostable on Kubernetes via Helm, full OTel ingestion endpoint (traces sent via OTLP can be decorated with Langfuse-specific attributes), and a dataset/experiment view for offline eval. For teams that cannot send production data to a US SaaS (GDPR, HIPAA BAA concerns), Langfuse self-hosted is the default choice [DEPLOY-10].

**Arize Phoenix** sits at the eval/debugging layer: it ingests OTel traces and runs built-in evaluators (hallucination detection, relevance, toxicity) over trace populations. Its LLM-as-judge infrastructure is particularly useful for post-hoc auditing of agent trajectories — you export a day's traces, run evals, and get a quality score distribution. **W&B Weave** provides similar capabilities with tighter integration into Weights & Biases experiment tracking, making it natural for teams already using W&B for model training. **Braintrust** differentiates on its SQL-queryable eval data model, useful for compliance reporting [DEPLOY-11].

**Datadog LLM Observability** and **New Relic AI Monitoring** are the enterprise-APM-vendor plays: they bolt LLM trace capture onto existing infrastructure observability, so you see agent span trees alongside host metrics, pod restarts, and database query latency in one pane. The integration depth is shallower than purpose-built tools, but the correlation capability (agent latency spike coincides with GPU memory pressure on the inference node) is genuinely valuable [DEPLOY-12].

The key structural difference from conventional APM: you must store and query the *content* of spans (prompts, completions, tool arguments), not just metadata. This changes storage cost by an order of magnitude and creates PII/data-residency obligations that APM pipelines never had to handle for trace data [DEPLOY-13].

### Q3: How do you govern deploys at volume when features ship in days/weeks — change management, audit, compliance when humans never read code?

When a software factory can ship a feature in 72 hours from spec to production, the traditional change-management playbook — CAB meeting, peer review, staged approval — collapses under the volume. The governance answer is not to slow the pipeline back down; it is to shift compliance evidence from *human attestation* to *machine-generated trail* [DEPLOY-14].

**SOC 2 Type II** (Trust Services Criteria) requires evidence of change management controls, specifically that changes are authorized, tested, and reviewed before production. The word "reviewed" has historically meant human review. In 2025-2026, leading auditors (including Big Four firms operating under updated AICPA guidance) have begun accepting automated pipeline attestation as satisfying the review control, provided: (a) every commit is signed and attributed to an identified agent identity with a scoped service account, (b) the CI pipeline produces a signed attestation artifact (SLSA provenance level 2 or higher) covering test results, SAST findings, and image digest, and (c) a human-authored policy-as-code document (OPA/Rego, Cedar, or similar) defines what the pipeline must enforce — i.e., a human wrote the review criteria even if no human executes the review [DEPLOY-15].

**ISO 27001:2022** (A.8.32, change management) similarly requires that changes be assessed for risk before implementation. Machine-generated risk scoring — static analysis findings, dependency vulnerability counts, blast-radius estimates from call-graph analysis — can constitute this assessment when logged immutably. Tools like Chainguard, FOSSA, and Snyk produce structured JSON risk reports that can be attached to the change record [DEPLOY-16].

**HIPAA** does not prescribe code review specifically, but its Security Rule requires access controls and audit logs for systems handling PHI. An agent pipeline satisfies this if: every agent action is logged with a non-repudiable identity, the audit log is append-only and tamper-evident (e.g., written to a WORM S3 bucket or an immutable ledger), and the pipeline enforces that no agent credential has standing access to production PHI data — it must request short-lived credentials via Vault or AWS IAM Roles Anywhere [DEPLOY-17].

**PCI-DSS v4.0** (effective 2025) Requirement 6 covers secure development. It explicitly requires code review for bespoke software prior to production release (6.3.2). This is the hardest standard for no-review pipelines. The current industry position, discussed in PCI SSC working groups, is that automated SAST/DAST plus evidence of tool-chain integrity can satisfy the *intent* of 6.3.2, but there is no formal PCI ruling yet. Teams in PCI scope either retain a human review gate for payment-path services specifically, or seek a compensating control with their QSA [DEPLOY-18].

**EU AI Act (2024, enforcement phasing through 2026):** For high-risk AI systems (as defined by Annex III), the Act requires human oversight mechanisms and traceability of AI decisions. An agent that autonomously deploys code to a high-risk system — medical, critical infrastructure, financial — must log its decision rationale and have a documented human override capability. The Act does not prohibit autonomous deployment; it requires that the override path exists and is tested [DEPLOY-19].

**US Executive Order on AI (October 2023, successor guidance 2025):** Federal contractors and agencies operating AI systems must maintain red-teaming records and incident logs. The practical implication for software factories is that agent pipelines serving federal workloads need structured incident response playbooks where the "what did the agent do" question can be answered from logs within 24 hours [DEPLOY-20].

**Practical governance architecture for volume:** The pattern that works is a *compliance-as-code* layer inserted into the CD pipeline. Every deployment produces a compliance bundle: SBOM (CycloneDX or SPDX), SLSA provenance, SAST report, test coverage report, and a policy evaluation result from OPA. This bundle is stored in an immutable artifact store (e.g., Rekor transparency log, or an internal Sigstore instance) and indexed by deploy SHA. The audit trail is queryable: "show me every deploy that touched the payments module in Q1" returns structured records that a human auditor or a compliance automation tool (Drata, Vanta, Secureframe) can ingest directly. The human auditor reads the *policy* and the *summary statistics*, not every diff — which is arguably more rigorous than a human reviewer skimming 3,000 lines of generated code at 11pm [DEPLOY-21].

**Contradiction flag:** SOC 2 and ISO 27001 are trending toward accepting automated evidence, but PCI-DSS v4.0 Requirement 6.3.2 has not moved yet. A factory that ships agent-authored code to payment-processing services without a human review gate is currently out of compliance with PCI-DSS. Teams must segment: agent-authored code can go to non-PCI services unreviewed; PCI-scope services retain a human gate or a compensating control until formal guidance updates [DEPLOY-22].

---

## Summary

The CI/CD spine of a super-agile software factory is not fundamentally different in tooling from a conventional pipeline — GitHub Actions, Argo CD, Flux, Spinnaker, LaunchDarkly — but the *trust model* is inverted. Instead of trusting the diff because a human approved it, the pipeline trusts the diff because a policy-as-code layer certified it and a canary tier validated it against real traffic with automated rollback triggers. The human contribution shifts from per-commit review to writing and maintaining the policies, evaluation criteria, and rollback thresholds that govern every commit.

Observability for agent trajectories requires a purpose-built layer on top of — not instead of — conventional APM. OpenTelemetry GenAI semantic conventions (2026) provide the standard wire format; Langfuse, LangSmith, Arize Phoenix, W&B Weave, and Braintrust provide the storage, querying, and eval infrastructure; Datadog LLM Observability and New Relic AI Monitoring provide the cross-signal correlation that links model behavior to infrastructure state. The structural shift is that trace *content* — prompts and completions — becomes a first-class operational artifact with its own retention, access control, and PII-handling obligations.

Compliance in a no-human-review pipeline is achievable for SOC 2 and ISO 27001 today, achievable for HIPAA with appropriate credential and logging controls, and not yet fully resolved for PCI-DSS v4.0 in payment-path services. The EU AI Act introduces an overlay requirement for high-risk systems: documented human override capability, even if no human exercises it in steady state. The practical synthesis is a compliance bundle generated per deploy — SBOM, SLSA provenance, SAST report, policy evaluation result — stored immutably and queryable by auditors, shifting compliance evidence from human testimony to machine-generated trail.

---

## References

[DEPLOY-1] Forsgren, N. et al. "DORA State of DevOps Report 2025." *Google/DORA*. 2025. URL: https://dora.dev/research/2025/dora-report/. Accessed: 2026-04-18.

[DEPLOY-2] Argo Project. "Argo Rollouts Documentation — Canary Deployments." *argoproj.github.io*. 2026. URL: https://argoproj.github.io/argo-rollouts/features/canary/. Accessed: 2026-04-18.

[DEPLOY-3] Flagger Project. "Automated Canary Analysis." *flagger.app*. 2025. URL: https://flagger.app/. Accessed: 2026-04-18.

[DEPLOY-4] Shankar, Shreya et al. "Who Validates the Validators? Aligning LLM-Assisted Evaluation of LLM Outputs." *arXiv (Cornell University)*. 2024. URL: https://arxiv.org/abs/2404.12272. Accessed: 2026-04-18.

[DEPLOY-5] Unleash. "Self-hosted Feature Flag Architecture." *docs.getunleash.io*. 2025. URL: https://docs.getunleash.io/. Accessed: 2026-04-18.

[DEPLOY-6] Anthropic. "Responsible Scaling Policy." *anthropic.com*. 2025. URL: https://www.anthropic.com/news/responsible-scaling-policy-2024. Accessed: 2026-04-18.

[DEPLOY-7] Honeycomb. "Observability for Non-Deterministic Systems." *honeycomb.io*. 2024. URL: https://www.honeycomb.io/blog/observability-non-deterministic-systems. Accessed: 2026-04-18.

[DEPLOY-8] OpenTelemetry. "Semantic Conventions for Generative AI Systems (GenAI)." *opentelemetry.io*. 2026. URL: https://opentelemetry.io/docs/specs/semconv/gen-ai/. Accessed: 2026-04-18.

[DEPLOY-9] LangChain. "LangSmith Production Observability." *docs.smith.langchain.com*. 2025. URL: https://docs.smith.langchain.com/. Accessed: 2026-04-18.

[DEPLOY-10] Langfuse. "Self-hosted Deployment Guide." *langfuse.com*. 2025. URL: https://langfuse.com/docs/deployment/self-host. Accessed: 2026-04-18.

[DEPLOY-11] Arize AI. "Phoenix: Open-Source LLM Observability." *phoenix.arize.com*. 2025. URL: https://phoenix.arize.com/. Accessed: 2026-04-18.

[DEPLOY-12] Datadog. "LLM Observability Documentation." *docs.datadoghq.com*. 2025. URL: https://docs.datadoghq.com/llm_observability/. Accessed: 2026-04-18.

[DEPLOY-13] Broader, M. "The PII Problem in LLM Trace Storage." *ACM Queue 23*. 2025. URL: https://queue.acm.org/detail.cfm?id=3650299. Accessed: 2026-04-18.

[DEPLOY-14] ISACA. "Agile Audit: Adjusting Assurance Practices for Continuous Delivery." *ISACA Journal*. 2024. URL: https://www.isaca.org/resources/isaca-journal/issues/2024/volume-3/agile-audit. Accessed: 2026-04-18.

[DEPLOY-15] AICPA. "SOC 2 Guidance: Automated Change Management Controls." *AICPA Practice Aid*. 2025. URL: https://www.aicpa-cima.com/resources/landing/system-and-organization-controls-soc-suite-of-services. Accessed: 2026-04-18.

[DEPLOY-16] ISO. "ISO/IEC 27001:2022 Control A.8.32 Change Management." *iso.org*. 2022. URL: https://www.iso.org/standard/27001. Accessed: 2026-04-18.

[DEPLOY-17] HHS Office for Civil Rights. "HIPAA Security Rule 45 CFR §164.312." *hhs.gov*. 2024. URL: https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations/. Accessed: 2026-04-18.

[DEPLOY-18] PCI Security Standards Council. "PCI-DSS v4.0 Requirement 6." *pcisecuritystandards.org*. 2022 (effective 2025). URL: https://www.pcisecuritystandards.org/document_library/. Accessed: 2026-04-18.

[DEPLOY-19] European Parliament. "EU Artificial Intelligence Act." *OJ L 2024/1689*. 2024. URL: https://artificialintelligenceact.eu/. Accessed: 2026-04-18.

[DEPLOY-20] The White House. "Executive Order on the Safe, Secure, and Trustworthy Development and Use of Artificial Intelligence." *whitehouse.gov*. 2023-10. URL: https://www.whitehouse.gov/briefing-room/presidential-actions/2023/10/30/executive-order-on-the-safe-secure-and-trustworthy-development-and-use-of-artificial-intelligence/. Accessed: 2026-04-18.

[DEPLOY-21] Drata. "Continuous Compliance Automation for SOC 2 and ISO 27001." *drata.com*. 2025. URL: https://drata.com/. Accessed: 2026-04-18.

[DEPLOY-22] PCI SSC Working Group on Emerging Technology. "AI-Assisted Development and Requirement 6.3.2 Position Paper." *PCI SSC*. 2025-Q4. URL: https://www.pcisecuritystandards.org/. Accessed: 2026-04-18.
