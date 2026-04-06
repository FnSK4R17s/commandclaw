# Devlog Instructions

How to add a new devlog entry at the end of a working session.

## When to write

At the end of any session that produced changes worth remembering — code fixes, design decisions, debugging journeys, infra changes, or notable observations. Skip purely exploratory sessions where nothing landed.

## Filename

`devlog/YYYY-MM-DD.md` — one file per day. If you work multiple sessions in a day, append to the existing file rather than creating a second one.

## Structure

```markdown
# Devlog — YYYY-MM-DD

## Summary
One paragraph: what the session was about and what shipped.

## Changes
Group by area (e.g. "Spawn pipeline", "MCP error handling", "Dockerfile").
For each change, lead with the problem, then the fix. Include file paths
or symbol names when they help future-you find the thing.

## Notes / observations
Anything surprising — perf numbers, gotchas, things that didn't work,
context that won't be obvious from the diff.

## TODO / followups
Loose ends, deferred work, or things to revisit. These are not promises,
just breadcrumbs.
```

## After writing

1. Add a row to [../DEVLOG.md](../DEVLOG.md) at the **top** of the table:
   ```markdown
   | [YYYY-MM-DD](devlog/YYYY-MM-DD.md) | One-line summary. |
   ```
2. Keep the summary under ~120 chars so the table stays readable.

## Tone

Write like you're leaving notes for yourself in three months. Concrete over abstract. Past-tense, first-person OK. Don't editorialize — record what happened and why.
