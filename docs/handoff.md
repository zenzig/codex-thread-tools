# Handoff Workflow

Monitor `WARN` threads and reassess them as work continues. Prepare a handoff
for `DANGER` threads once any active turn is complete.

Use `codex-thread-handoff` when:

- the health check says `DANGER`
- a monitored `WARN` has persisted or worsened and you decide to rotate the thread
- a major implementation slice is complete
- Codex reports a context-window or compaction error
- the model starts losing track of earlier decisions
- you want to start a new thread without losing project context

The skill writes a handoff file in the project repository. A good handoff keeps
durable facts outside the chat:

- current task and next action
- branch and commit
- changed files
- decisions made
- commands/tests already run
- known risks and failures
- exact prompt to paste into a new Codex thread
- sidecar and prompt markers that retire the old session and connect the new thread

Compaction helps Codex continue a conversation. A handoff helps a new thread
resume the project.

## Quick Flow

1. Run `codex-thread-tools health`.
2. If health is `WARN`, monitor the thread and reassess it as work continues.
3. If health is `DANGER`, finish the active turn and ask Codex to use
   `codex-thread-handoff`.
4. Review the generated handoff file in your project repository.
5. Start a fresh Codex thread with the prompt from that handoff.
6. Continue from durable repository notes, not from the old oversized session.

## Handoff Summary Draft

To generate a read-only, redacted summary draft for one session:

```bash
codex-thread-tools handoff-summary ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

The draft includes health, pre-handoff safety, compaction state, visual counts,
and concise user/assistant context. It omits raw tool payloads, compacted
payloads, and common secret-shaped values. Treat it as a starting point for the
repo-backed handoff file, not as final project memory.

## Security Boundary

The handoff summary uses best-effort redaction. Tool payloads and compacted
record contents are omitted, then known secret patterns are redacted before text
normalization. This protects common token/key/password surfaces (environment
assignments, authorization headers, credentials in URIs, PEM blocks, and known
vendor key formats) as a guardrail, not a security boundary.

Arbitrary encoded content, unknown formats, or secrets that don't match known
patterns aren't reliably classified as sensitive. This is best-effort redaction,
not proof that a summary is clean. Always review before sharing, committing, or
using a generated summary for a manual handoff.

## Handoff Markers

Completed handoffs are tracked in a local sidecar marker file under
`~/.codex/thread-tools/`. Project health reports use those markers to retire old
source sessions and prioritize the new active replacement thread. Reports also
include the running total of completed handoffs per project.

To record a completed handoff marker manually:

```bash
codex-thread-tools handoff-marker record \
  --source-session-file ~/.codex/sessions/YYYY/MM/DD/thread.jsonl \
  --replacement-session-file ~/.codex/sessions/YYYY/MM/DD/new-thread.jsonl \
  --handoff-file /path/to/project/handoffs/YYYY-MM-DD-topic.md
```

The command appends one local sidecar event and prints a `Codex thread handoff
marker:` block to include in the new thread prompt. The marker file is local
state; do not commit it.

You can also run this command after an older handoff to backfill the local
sidecar marker. Backfilling records local state only; it does not modify Codex
session JSONL. For older handoffs that did not include the prompt marker in the
new thread, pass `--replacement-session-file` so health reports can show which
active session replaced the retired source.

## Codex Remote Handoff Is Different

Codex also has a remote-connections handoff feature that moves the same active
thread and its Git state between your local computer and a connected remote
host. That is useful when you want to keep working in the same thread, but run
it somewhere else.

`codex-thread-handoff` is for a different problem: retiring or rotating a large,
risky, or completed project thread while preserving durable project context in
your repository. It writes a handoff file, records health findings, captures
visual archive decisions, and gives you the prompt and markers needed to start a
fresh thread with the right project context.

You can use both together. Use Codex remote handoff for host placement. Use
`codex-thread-tools` for thread health, repo-backed continuity, and safer thread
rotation.
