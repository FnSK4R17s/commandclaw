# <Feature Name>

> <One sentence that captures the entire feature — what changes, for whom, why it matters.>

This is an idea file. It describes a feature for an existing codebase at the
right level of abstraction — concrete enough to be actionable, abstract enough
to not over-specify implementation. Share it with an implementing LLM agent
alongside the three stage files under `plan/<slug>/` and let the agent
propose a concrete patch plan before writing any code.

## What changes

Describe what the system does today and why that is insufficient. Then
describe what the system does after this feature and why. Use concrete file
paths and module names from Stage 1. **Bold the sentence that captures the
core shift** — the one observation about the current code that makes this
feature obvious in hindsight.

Today, `<module/path.ext>` handles `<behavior>` by `<mechanism>`. This is
insufficient because `<gap>`. After this feature, `<module/path.ext>` handles
`<behavior>` by `<new mechanism>`, and `<new module/path.ext>` owns
`<new responsibility>`.

## Touchpoints

The modules this feature adds, changes, or depends on. Each is a bold-named
layer with a one-paragraph description. Describe *what* each layer does in
this feature and *why*, not *how*.

**`<module/path.ext>`** — what this module's role is in the new behavior
and why it is the right home for that role. One paragraph. Reference the
existing code it extends.

**`<module/path.ext>`** — …

**`<new/module/path.ext>`** — the new module introduced by this feature,
its role, and why it is a new module rather than an extension of an
existing one.

## Workflow

The 1–3 user- or caller-triggered flows through the new behavior. Numbered
steps, one sentence each, high-level.

### <Flow name — e.g. "User imports a CSV">

1. …
2. …
3. …

### <Second flow if the feature has more than one entry point>

1. …
2. …

## Example

One specific instance of the feature in action. Pick a concrete user, a
concrete input, and a concrete output. Include sample data, sample request,
and sample response. This grounds the abstract touchpoints and workflow.

> **Scenario.** A `<concrete user>` does `<concrete action>` with `<concrete
> input>`.

Input:

```
<sample data / request body / CLI invocation>
```

What happens:

1. …
2. …
3. …

Output:

```
<sample response / resulting state / user-visible result>
```

## Stack

The components this feature touches. Status values: `Built` (already in
repo), `Available` (library installed, not yet used for this feature),
`To build` (new).

| Component | Technology | Status |
|-----------|-----------|--------|
| … | … | … |
| … | … | … |

## Acceptance criteria

Lifted from Stage 2. Do not soften or rephrase — these are the contract.

- [ ] …
- [ ] …
- [ ] …

## Out of scope

Explicitly not part of v1. Lifted from Stage 2.

- …

## What makes this hard

Two to four genuine challenges from Stage 3. Each is 2–3 sentences: why it is
hard, and a mitigation sketch. Be honest. Do not hand-wave.

1. **<Challenge>** — why it is hard. Mitigation sketch.
2. **<Challenge>** — why it is hard. Mitigation sketch.

## Why this works

One paragraph. Connect the shape of this feature to a deeper observation
about the existing codebase or the user's workflow — the reason this
approach succeeds where a naive version would not. Reference prior art in
the repo if relevant. **Bold the closing insight.**

## References

The implementing agent should read these before starting:

- [Research](01-research.md)
- [Requirements](02-requirements.md)
- [Deep Research](03-deep-research.md)

## Note

This document is intentionally abstract. Concrete file edits, function
signatures, and test cases depend on the state of the codebase at
implementation time. Paste this document into an implementing agent's
context along with the three referenced stage files, and let the agent
propose a concrete patch plan before writing code.
