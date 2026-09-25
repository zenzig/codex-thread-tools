# Recovery

Use recovery tools when a thread is hard to load, has disappeared from the
sidebar, has hit a compaction/context error, or has a malformed model-visible
image input. Start with the read-only diagnosis rather than attempting to edit
the session history.

## Safe Recovery

Diagnose the session without modifying it:

```bash
agent-thread-tools recover diagnose ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

Use `--json` for scripts. A clean report exits `0`, a caution-only report exits
`2`, and an unsafe replay input exits `3`.

Diagnosis checks canonical message image inputs and the image items carried in
Codex `custom_tool_call_output` and `function_call_output` records. Those
outputs can become part of a later replayed model input. It deliberately does
not treat arbitrary `image_url` keys in tool payloads or tool schemas as a
replay defect.

When diagnosis recommends a bundle, create a sanitized recovery artifact next:

```bash
agent-thread-tools recover bundle \
  ~/.codex/sessions/YYYY/MM/DD/thread.jsonl \
  --project-root /path/to/project
```

The bundle is written outside `~/.codex/sessions` by default and does not modify the source session. It contains a structural integrity report, a redacted
handoff template, a fresh-task prompt, a visual decision record, and an
integrity manifest. It never copies the source JSONL into the bundle. Use
`--output-root /path/to/recovery-bundles` to choose another external location.

If a session contains relevant screenshots or generated assets, review the
bundle's visual decision and run `agent-thread-tools visual-archive scan` before
retiring the session.

## Claude Code

The same commands read Claude Code sessions; the tool detects the format from the
file:

```bash
agent-thread-tools recover diagnose ~/.claude/projects/<project>/<session>.jsonl
```

For Claude Code, diagnosis also reports tool calls that never got a result and API
errors about images. When Claude Code cannot process an image in a session, the
request fails, and Claude Code drops the image and continues, but only in memory,
so every resume repeats the failed request. `strip-images` removes such images
from the file for good:

```bash
agent-thread-tools recover strip-images <session>.jsonl --output /tmp/repaired.jsonl
agent-thread-tools recover strip-images <session>.jsonl --replace-live \
  --confirm-replace-live <session>.jsonl
```

Each broken image becomes a short text note and every other line stays unchanged.
`--all` replaces every image, for example after an API error about image size.
Exit the session (or run `/clear` in it) first: writes are refused while it is
open. Backups go to `~/.claude/thread-tools/session-backups/` and bundles to
`~/.claude/thread-tools/recovery-bundles/` unless you choose other folders.

`strip-compacted` and `rebuild-window` rewrite Codex records and refuse Claude
Code sessions. For Claude Code, a handoff followed by `/clear` does the same job.

## Legacy Operations

`inspect`, `backup`, `strip-compacted`, and `rebuild-window` remain available
for advanced recovery work:

```bash
agent-thread-tools recover inspect ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

Before any repair, make a backup:

```bash
agent-thread-tools recover backup ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

`strip-compacted` and `rebuild-window` are legacy write operations. They do not
repair malformed persisted image data. Use them only after a backup and manual
inspection, and prefer a fresh task with a recovery bundle when the goal is a
safe continuation.

## Legacy Safety Guards

The recovery tool is intentionally conservative:

- repair output cannot be written into `~/.codex/sessions/` or `~/.claude/projects/`
- live replacement requires `--replace-live`
- live replacement also requires `--confirm-replace-live` with the exact resolved path
- write operations refuse to run while Codex appears to be open, or while the
  Claude Code session is open

Treat legacy repair commands as last-resort tools. Back up before any write and
prefer writing repaired output to a scratch path before replacing a live session
file.
