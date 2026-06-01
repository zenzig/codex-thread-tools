---
name: codex-thread-handoff
description: Use when a user asks to hand off, preserve project context, finish a major slice, or continue from a risky long Codex thread.
---

# Codex Thread Handoff

## Goal

Move durable project memory out of the chat log and into the repository or workspace before a thread becomes too large to load, compact, or continue.

## Default

When invoked, perform the workflow. Ask only if the project root is unclear, a write would overwrite an existing handoff, the active session file is needed for visual archiving, or the user must choose an archive location.

Load `references/handoff-workflow.md` and `references/handoff-template.md`, then write a concise handoff and a fresh-thread prompt. Do not dump the full transcript.

## Required Checks

- Identify the project root and current git state before writing.
- Run `tools/codex-thread-health.py` when available. Exit code `2` is `WARN`; exit code `3` is `DANGER`; both are reportable health results, not shell failures.
- Prefer the health check's recommendation over a simple "compaction happened" rule. A successful compaction alone is not a handoff requirement.
- If visuals are present or mentioned, record an explicit visual archive decision in the handoff: archived manifest paths, or `Not archived:` with the reason. Do not silently skip visual context.
- Include exact paths, branch/commit, changed files, decisions, verification commands, risks, and next action.
- Verify the handoff exists and is readable before responding.

## Boundaries

Do not claim to open or switch to a new Codex thread unless a tool does that and succeeds. If no such tool is available, give the user the exact prompt for the new thread.

Treat git, tests, repo docs, archive manifests, and handoff files as the durable memory layer. Do not treat the chat transcript or opaque compaction items as durable project notes.

## When To Recommend Handoff

- the thread health report says `handoff-now`
- `codex-thread-health` reports `danger`, or reports `warn` and the next slice will be substantial
- Codex reports context-window or compaction errors
- a major implementation slice is complete
- the task has produced many tool calls, screenshots, recordings, or long outputs
- the model starts losing track of recent context
- the user is about to begin a distinct next slice
