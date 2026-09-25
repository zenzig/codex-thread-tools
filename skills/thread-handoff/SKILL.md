---
name: thread-handoff
description: Distil a long Claude Code session into a durable handoff (decisions, state, reference docs, screenshots) so a fresh session continues the project without the old transcript. Use when the user asks to hand off, preserve context, or start fresh, or when thread health reports warn/danger.
---

# Thread Handoff (Claude Code)

## Goal

Move durable project memory out of the transcript and into files that every new
session loads automatically, so the next session (any model) starts effective
without re-explaining the project or replaying history.

## Locate the session

This session's transcript is `~/.claude/projects/*/${CLAUDE_SESSION_ID}.jsonl`.
Resolve it with `ls ~/.claude/projects/*/${CLAUDE_SESSION_ID}.jsonl`. If that
fails, use the newest `*.jsonl` in the project's `~/.claude/projects/<dir>/`.

## Where things go

Everything goes in the project's `.reference/` folder: a local-only git repository,
hidden from the project repository, never pushed. Step 1 creates it when missing.

- Handoffs: `.reference/handoffs/YYYY-MM-DD-short-topic.md`, from
  `references/handoff-template.md`.
- Screenshots: `.reference/` is the visual archive root.
- Large pasted text or Markdown worth keeping: `.reference/docs/`, one file each,
  listed in `.reference/INDEX.md` with a one-line description.

## Workflow

1. Set up: run `codex-thread-tools reference init` from the project root. It creates
   `.reference/` as a local git repository and hides it from the project repository.
   Then inspect: `git status --short`, `git log --oneline -8`, relevant diffs.
2. Health: `codex-thread-tools health check <session-file>`. Exit `2` is WARN and `3`
   is DANGER; both are results, not failures.
3. Draft: `codex-thread-tools handoff-summary <session-file>` as a redacted aid. Verify
   every important fact against files, git, tests, or explicit user instructions.
4. Visuals: if screenshots exist, `codex-thread-tools visual-archive scan <session-file>`,
   then archive the ones that still matter:
   `codex-thread-tools visual-archive archive --archive-root .reference --project-name <name> --artifact-set <YYYY-MM-DD-topic> --visual-context "<what they show>" <session-file>`.
   Record `Archived:` with the manifest path, or `Not archived:` with the reason.
5. Reference docs: save large user-provided text or Markdown that later work depends
   on into `.reference/docs/` and update `INDEX.md`.
6. Write the handoff. Put stable, long-lived facts (architecture, conventions,
   commands) into the project `CLAUDE.md` instead, kept short; put per-slice state in
   the handoff.
7. Wire it in: keep exactly one line in `CLAUDE.local.md` (create it if missing):
   `Latest handoff: @<handoff path>` and `Reference index: @.reference/INDEX.md`.
   Replace the previous line; never accumulate old handoffs there.
8. Commit: `codex-thread-tools reference commit -m "Handoff: <topic>"`. Do not commit
   to the project repository unless the user asks.
9. Mark: `codex-thread-tools handoff-marker record --source-session-file <session-file> --handoff-file <handoff path>`.
10. Report the handoff path and tell the user to run `/clear` (or open a new session).
    The new session loads the handoff through `CLAUDE.local.md` automatically.

## Boundaries

Do not dump the transcript, raw tool output, or base64 media into any file. Do not
claim the new session started; the user starts it. Treat git, tests, CLAUDE.md,
handoffs, and archive manifests as the durable memory, not the transcript.

## When to recommend a handoff

- health reports `danger`, or `warn` before a substantial next slice
- a major slice is complete or a distinct next slice is starting
- many screenshots, long outputs, or repeated compactions
- the model starts losing track of earlier decisions
