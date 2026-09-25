# Recovery

Use recovery tools when a session is hard to load, has hit a compaction or
context error, keeps failing on an image, or has disappeared from the Codex
sidebar. Every command reads Claude Code and Codex sessions; the format is
detected from the file. Start with the read-only diagnosis rather than editing
the session history.

## Diagnose

Diagnose the session without modifying it:

```bash
agent-thread-tools recover diagnose ~/.claude/projects/<project>/<session>.jsonl
agent-thread-tools recover diagnose ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

Use `--json` for scripts. A clean report exits `0`, a caution-only report exits
`2`, and an unsafe replay input exits `3`.

Diagnosis checks image inputs in messages and the images carried in tool results
(Codex `custom_tool_call_output` and `function_call_output` records, and Claude
Code `tool_result` blocks). Those can become part of a later replayed model
input. It deliberately does not treat arbitrary `image_url` keys in tool payloads
or tool schemas as a replay defect.

What the result means depends on the agent:

- Claude Code: a broken image, or an API error about an image recorded in the
  session, is a caution, and the recommended action is `strip-images` (below).
  Diagnosis also reports tool calls that never got a result.
- Codex: a malformed or remote image input is unsafe, and the recommended action
  is a recovery bundle.

## Recovery Bundle

When diagnosis recommends a bundle, create a sanitized recovery artifact next:

```bash
agent-thread-tools recover bundle \
  ~/.codex/sessions/YYYY/MM/DD/thread.jsonl \
  --project-root /path/to/project
```

The bundle is written outside `~/.codex/sessions` and `~/.claude/projects` by
default and does not modify the source session. Codex bundles go to
`~/.codex/thread-tools/recovery-bundles/` and Claude Code bundles to
`~/.claude/thread-tools/recovery-bundles/`. Use
`--output-root /path/to/recovery-bundles` to choose another external location.

A bundle contains a structural integrity report, a redacted handoff template, a
prompt for starting a fresh session in the same agent, a visual decision record,
and an integrity manifest. It never copies the source JSONL into the bundle.

If a session contains relevant screenshots or generated assets, review the
bundle's visual decision and run `agent-thread-tools visual-archive scan` before
retiring the session.

## Strip Images (Claude Code)

When Claude Code cannot process an image in a session, the request fails, and
Claude Code drops the image and continues, but only in memory, so every resume
repeats the failed request. `strip-images` removes such images from the file for
good:

```bash
agent-thread-tools recover strip-images <session>.jsonl --output /tmp/repaired.jsonl
agent-thread-tools recover strip-images <session>.jsonl --replace-live \
  --confirm-replace-live <session>.jsonl
```

Each broken image becomes a short text note and every other line stays unchanged.
`--all` replaces every image, for example after an API error about image size.
Exit the session (or run `/clear` in it) first: writes are refused while it is
open. `strip-images` refuses Codex sessions.

## Inspect And Back Up

`inspect` summarizes a session file: record counts, the largest lines, and for
Claude Code also images, tool calls, compactions, and API errors.

```bash
agent-thread-tools recover inspect <session>.jsonl
```

Before any repair, make a backup (a hard link when possible, otherwise a copy):

```bash
agent-thread-tools recover backup <session>.jsonl
```

Backups go to `~/.claude/thread-tools/session-backups/` for Claude Code and
`~/.codex/session_quarantine/` for Codex, unless you pass `--backup-dir`.

## Legacy Codex Operations

`strip-compacted` and `rebuild-window` rewrite Codex records and are available
for advanced Codex recovery work only. They refuse Claude Code sessions; for
Claude Code, a handoff followed by `/clear` does the same job.

`strip-compacted` and `rebuild-window` are legacy write operations. They do not
repair malformed persisted image data. Use them only after a backup and manual
inspection, and prefer a fresh task with a recovery bundle when the goal is a
safe continuation.

## Safety Guards

The recovery tool is intentionally conservative:

- repair output cannot be written into `~/.codex/sessions/` or `~/.claude/projects/`
- live replacement requires `--replace-live`
- live replacement also requires `--confirm-replace-live` with the exact resolved path
- live replacement makes a backup first
- write operations refuse to run while Codex appears to be open, or while the
  Claude Code session is open

Treat repair commands as last-resort tools. Back up before any write and prefer
writing repaired output to a scratch path before replacing a live session file.
