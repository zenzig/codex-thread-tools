# Thread Health

The main command is:

```bash
codex-thread-tools health
```

It scans your Codex session folder, finds the most recent session for each
project, and reports whether each thread looks safe to continue.

## Statuses

| Status | Meaning | What to do |
| --- | --- | --- |
| `OK` | No major risk signals were found. | Keep working. |
| `WARN` | One risk area needs attention. | Continue, but prepare a handoff if the task will keep growing. |
| `DANGER` | Strong risk signals were found. | Make a handoff and start a fresh thread. |
| `RETIRED` | The session was already handed off and is no longer active. | Use the replacement thread or the handoff file. |

The health check is read-only. It does not edit, delete, trim, or repair any
Codex thread.

## Display Modes

The default human report is table-first and uses exact byte counts.

Compact dashboard:

```bash
codex-thread-tools health --mode compact
```

Full diagnostic output:

```bash
codex-thread-tools health --mode verbose --size-format both
```

`--size-format` accepts `bytes`, `human`, or `both`.

For machine-readable output:

```bash
codex-thread-tools health --json
```

JSON output ignores pretty display options and is the stable scripting
interface.

## Progress

Large screenshot-heavy sessions can take a while to parse. In an interactive
terminal, progress is printed on stderr. If your terminal or editor hides
stderr, force progress output:

```bash
codex-thread-tools health --progress always
```

## What Health Checks Inspect

- session file size
- number of response items
- number of `compacted` checkpoints
- whether the latest compacted checkpoint has `replacement_history`
- whether compaction signals are only requests or installed continuation state
- compaction warning or error events
- active, incomplete, aborted, and error turns
- active token usage, when Codex persisted it
- embedded screenshots, videos, and visual references
- whether compacted records dominate the file size

## Risk Domains

| Risk area | What it checks |
| --- | --- |
| `Load` | Disk size and unusually large JSONL records. |
| `Visuals` | Embedded screenshots/videos, missing visual files, and visuals inside compacted history. |
| `Compaction` | Failed, malformed, legacy, request-only, installed, or repeatedly stressed compaction state. |
| `Limits` | Response item count and active context-window pressure. |
| `Continuity` | Missing session metadata, active incomplete turns, unresolved aborted turns, or error events. |

Historical abort or error events are treated differently from unresolved ones.
If a later `turn_complete` or `task_complete` event is persisted, the health
check reports the historical abort/error as `WARN` instead of `DANGER`. If the
latest terminal event is still an abort or error, it remains `DANGER`.

If a `turn_started` event has no later completion, abort, or error event, the
thread is reported as `WARN`. That usually means Codex was still working or the
turn did not persist a clean terminal state, so a handoff should not be treated
as clean yet.

## One Session

To check one specific session file:

```bash
codex-thread-tools health check ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

## Token Usage

To estimate Codex-persisted lifetime token usage by project:

```bash
codex-thread-tools health tokens
```

You can choose the same display modes for token reports:

```bash
codex-thread-tools health tokens --mode standard
```

The token report scans session JSONL files under `~/.codex/sessions/`, groups
them by project, and sums the latest cumulative `token_count` total from each
token-bearing session. It also shows the latest active token estimate and active
context percentage for each project.

Use JSON when you want the per-session source records behind each project total:

```bash
codex-thread-tools health tokens --json
```

Treat this as a Codex session-scale report, not a billing ledger. Older
sessions may not contain `token_count` events, and missing token data is
reported as `not recorded` rather than guessed as zero.
