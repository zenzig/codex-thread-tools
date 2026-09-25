# Handoff Workflow

A handoff ends a long session on purpose. The durable project facts go into a
short handoff file, and a fresh session starts from that file instead of the old
transcript. Compaction helps a session keep going; a handoff helps a new session
resume the project.

Monitor `WARN` sessions and reassess them as work continues. Prepare a handoff
for `DANGER` sessions once any active turn is complete.

Hand off when:

- the health check says `DANGER`
- a monitored `WARN` has persisted or worsened and you decide to rotate the session
- a major piece of work is complete
- the agent reports a context-window or compaction error
- the model starts losing track of earlier decisions
- you want to start a new session without losing project context

A good handoff keeps durable facts outside the chat:

- current task and next action
- branch and commit
- changed files
- decisions made, and why
- commands and tests already run
- known risks and failures
- screenshots worth keeping, archived with a manifest

## Claude Code

Install the skill once with `agent-thread-tools install-skill --agent claude`
(see [Installation](installation.md)). Then:

1. Run `agent-thread-tools health --agent claude`.
2. If health is `WARN`, keep working and check again at the next break.
3. If health is `DANGER`, or a piece of work is done, run `/thread-handoff` in that
   session.
4. Read the handoff it writes and correct anything wrong.
5. Run `/clear` or open a new session. It starts with the handoff already loaded.

The skill writes a dated handoff to `.reference/handoffs/`, archives screenshots
that still matter into `.reference/`, puts stable facts into `CLAUDE.md`, and
points `CLAUDE.local.md` at the latest handoff. `.reference/` is a local git
repository that is never pushed. See [Claude Code](claude-code.md) for the
details.

## Codex

Install the skill once with `agent-thread-tools install-skill`. Then:

1. Run `agent-thread-tools health`.
2. If health is `WARN`, monitor the thread and reassess it as work continues.
3. If health is `DANGER`, finish the active turn and send the exact
   repository-backed request below in that thread.
4. Review the generated handoff file in your project repository.
5. Start a fresh Codex thread with the prompt from that handoff.
6. Continue from durable repository notes, not from the old oversized session.

The request to send:

```text
Use the installed `codex-thread-handoff` skill to create a repository-backed
handoff for a new task. Do not use Codex's native Handoff or `handoff_thread`.
If the skill is unavailable, stop and report that it must be installed.
```

The Codex handoff also contains the exact prompt to paste into the new thread,
including the marker block that connects the new thread to the old one.

## Handoff Summary Draft

To generate a read-only, redacted summary draft for one session:

```bash
agent-thread-tools handoff-summary ~/.claude/projects/<project>/<session>.jsonl
agent-thread-tools handoff-summary ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

Both skills use this draft when they can locate the session file. It includes
health, pre-handoff safety, compaction state, visual counts, and concise user and
assistant context. It omits raw tool payloads, compacted payloads, and common
secret-shaped values. Treat it as a starting point for the handoff file, not as
final project memory.

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

Completed handoffs are tracked in a local sidecar marker file. One file serves
both agents: `~/.codex/thread-tools/handoff-markers.jsonl` when Codex is
installed, otherwise `~/.claude/thread-tools/handoff-markers.jsonl`. Set
`AGENT_THREAD_HANDOFF_MARKER_FILE` to use another file. The marker file is local
state; do not commit it.

Health uses the markers to link sessions. The session that was handed off shows
as retired, and its replacement shows as active. Reports also include the running
total of completed handoffs per project. How the replacement is found depends on
the agent:

- Claude Code: a later session that loaded the handoff through `CLAUDE.local.md`
  is its replacement. Nothing needs to be pasted.
- Codex: the new thread's prompt contains the `Codex thread handoff marker:`
  block, or the marker names the replacement session.

Both skills record the marker. To record one manually:

```bash
agent-thread-tools handoff-marker record \
  --source-session-file ~/.claude/projects/<project>/<session>.jsonl \
  --handoff-file /path/to/project/.reference/handoffs/YYYY-MM-DD-topic.md
```

The command appends one local sidecar event and prints a `Codex thread handoff
marker:` block. Codex users include that block in the new thread prompt; Claude
Code users can ignore it.

You can also run this command after an older handoff to backfill the local
sidecar marker. Backfilling records local state only; it does not modify any
session JSONL. For an older Codex handoff that did not include the prompt marker
in the new thread, pass `--replacement-session-file` so health reports can show
which active session replaced the retired source.

## Codex Remote Handoff Is Different

Codex also has a remote-connections handoff feature that moves the same active
thread and its Git state between your local computer and a connected remote
host. That is useful when you want to keep working in the same thread, but run
it somewhere else.

`codex-thread-handoff` is for a different problem: retiring or rotating a large,
risky, or completed project thread while preserving durable project context in
your repository. It never calls `handoff_thread`, and it does not transfer the
active task. It writes a handoff file, records health findings, captures visual
archive decisions, and gives you the prompt and markers needed to start a fresh
thread with the right project context.

You can use both together. Use Codex remote handoff for host placement. Use
`agent-thread-tools` for session health, repo-backed continuity, and safer
session rotation.
