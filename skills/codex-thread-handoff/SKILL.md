---
name: codex-thread-handoff
description: Automatically create durable repo-backed handoff files and clean-thread continuation prompts for Codex workflows. Use when the user references this skill, says to hand off the current thread, says to prepare/start a new thread, a long Codex thread is becoming large, compaction has happened, a major task or slice is complete, or Codex needs to preserve project memory before archiving or moving on.
---

# Codex Thread Handoff

## Goal

Move durable project memory out of the chat log and into the repository or workspace before a thread becomes too large to load, compact, or continue.

## Default Behavior

When the user references this skill, immediately perform the handoff workflow. Do not ask for confirmation unless the project root cannot be determined or writing the handoff would risk overwriting an existing file.

The expected user input can be as short as:

```text
Use codex-thread-handoff.
```

Treat that as a request to inspect the current thread/project, write a handoff file, and provide the exact prompt for a fresh thread.

## Workflow

1. Identify the active project root with `pwd`, `git rev-parse --show-toplevel`, or the user-provided path.
2. When `tools/codex-thread-health.py` exists in the skill repo, run a read-only health check before writing:
   - `python3 tools/codex-thread-health.py`
   - Exit code `2` means `WARN`; exit code `3` means `DANGER`. Treat those as health results, not command failures.
   - If it reports `WARN` or `DANGER`, include the overall status, recommendation, top reasons, and domain risk breakdown (`Load`, `Visuals`, `Compaction`, `Limits`, `Continuity`) in the handoff.
   - Do not treat a single successful compaction as a handoff requirement by itself. Prefer the health check's recommendation over a simple "compacted happened" rule.
   - Do not run health checks in `--safe-test-mode` unless using fixture or scratch session roots; safe test mode intentionally refuses the live Codex session tree.
3. If the health check reports visual references, the user mentions screenshots/videos, or the thread contains visual design work, prepare a visual archive before writing:
   - Run `python3 tools/codex-visual-archive.py scan <session-file>` when the active session file is known.
   - If visuals should be retained, ask the user for an archive location such as an external drive folder, then run `python3 tools/codex-visual-archive.py wizard <session-file>` or the non-interactive `archive` command.
   - Reference `manifest.md`, `manifest.json`, and `handoff-snippet.md` in the handoff. Do not embed base64 image or video data in the handoff.
   - If the session file cannot be identified, ask the user for the specific session path rather than guessing.
4. Inspect current work state before writing:
   - `git status --short`
   - recent commits when relevant: `git log --oneline -8`
   - focused diffs or changed-file summaries when there are uncommitted changes.
5. Choose a handoff path:
   - Prefer an existing project convention if present, such as `documentation/agent-handoffs/`, `docs/handoffs/`, or `notes/handoffs/`.
   - Otherwise create `documentation/agent-handoffs/`.
   - Use a filename like `YYYY-MM-DD-short-topic.md`.
6. Load `references/handoff-template.md` and write a concise handoff. Do not dump the full conversation.
7. Include enough concrete handles for a fresh Codex thread to resume:
   - project path and branch
   - current task and next action
   - decisions made
   - files changed or likely relevant
   - commands/tests already run
   - known failures, risks, or open questions
   - archived screenshots/videos by manifest path and absolute archived file paths, not embedded base64
8. Add a short "new thread prompt" at the bottom that the user can paste into a fresh Codex thread.
9. Verify the handoff file exists and is readable. If the repo is under git, report whether it is staged, committed, or left uncommitted.
10. End with a minimal final response containing:
   - the handoff file path
   - whether the file is committed/staged/uncommitted
   - the exact new-thread prompt in a fenced code block

## New Thread Boundary

Do not claim to have opened or switched to a new Codex thread unless a tool explicitly provides that capability and the action succeeds.

If no such tool is available, prepare everything needed for the new thread and tell the user to open a new thread with the provided prompt. The prompt must reference the handoff file by absolute path so the next agent can resume without loading the previous chat.

## Handoff Quality Bar

Write for a capable agent with no access to the previous chat. The handoff should be short enough to load into a new thread, but specific enough that the next agent does not need to reconstruct the last several hours from scratch.

Prefer exact file paths, commit hashes, test names, commands, error text, and decisions. Avoid vague phrases like "various files" or "fixed the issue" unless paired with concrete evidence.

## Thread Hygiene Guidance

Recommend a handoff and new thread when any of these are true:

- the thread health report says `handoff-now`
- the thread has repeated compaction plus warning, error, or quality-risk signals
- the task has produced many tool calls, screenshots, or long outputs
- the thread contains important screenshots, screen recordings, or other visual references that should be archived before the old thread is retired
- a major implementation slice is complete
- the model starts losing track of recent decisions
- Codex reports context-window or compaction errors
- `codex-thread-health` reports `danger`, or reports `warn` and the next task slice will be substantial
- the user is about to begin a distinct next slice

Do not treat the chat transcript as the durable project record. Use git, tests, repo docs, and handoff files as the durable memory layer.
