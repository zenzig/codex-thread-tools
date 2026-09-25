# Thread Health

The main command is:

```bash
agent-thread-tools health --agent claude    # Claude Code sessions in ~/.claude/projects/
agent-thread-tools health --agent codex     # Codex sessions in ~/.codex/sessions/
```

Without `--agent`, health reads Codex sessions when `~/.codex/sessions/` exists
and Claude Code sessions otherwise. `--session-root` points it at any other
folder.

Health scans the session folder, selects the newest non-retired user-owned root
session for each project, and reports whether it looks safe to continue. A newer
subagent or automation session does not replace that root in the project report.
Claude Code subagent transcripts, which live in the session's own folder, are
skipped entirely. If a project has no root session, the newest available child
session is used as a fallback. A selected session can be old; guidance applies if
you intend to resume that exact session.

## Statuses

| Status | Meaning | What to do |
| --- | --- | --- |
| `OK` | No major risk signals were found. | Keep working. |
| `WARN` | One risk area needs attention. | Monitor the selected session; a handoff is not currently required. |
| `DANGER` | Strong risk signals were found. | Handoff before continuing. |
| `RETIRED` | The session was already handed off and is no longer active. | Use the replacement session or the handoff file. |

Turn state and continuation risk are separate. The `Overall` line and `Status`
column retain the aggregate domain severity used by JSON and exit codes. The
separate `Turn`, `Risk`, and `Action` columns
explain what that severity means operationally. A session can have an active turn
or a historical warning and still be safe to continue.

| Turn State | Continuation Risk | Handoff Lineage | Action |
| --- | --- | --- | --- |
| `active` | `ok` | Any | Finish the current turn, then continue. |
| Any | `watch` | Any | Monitor the session; a handoff is not currently required. |
| Any | `danger` | Any | Handoff before continuing. |
| Any | Any | `source-retired` | Use the replacement session or handoff summary. |

For historical compacted visual references, the report emits notice-level output by
themselves so they can be reviewed without being treated as unsafe continuity
signals. Successful installed compaction counts are also scale information:
crossing the configured compaction review threshold produces `NOTICE`, not
continuation risk. Failed or malformed compaction state can still produce
`WARN` or `DANGER`.

The health check is read-only. It does not edit, delete, trim, or repair any
session file.

## Display Modes

The default human report is table-first and uses exact byte counts.

Compact dashboard:

```bash
agent-thread-tools health --mode compact
```

Standard table output:

```bash
agent-thread-tools health --mode standard
```

Full diagnostic output:

```bash
agent-thread-tools health --mode verbose --size-format both
```

`--size-format` accepts `bytes`, `human`, or `both`.
Verbose output labels compatibility-only continuation and handoff-readiness
fields as `Legacy`; use the state-first `Risk` and `Action` values for the
current guidance.

For a single session, standard output shows measured file size and its warning
threshold, response items and their warning threshold, installed compaction
checkpoints, and visual references. Request-only compaction records do not count
as installed checkpoints.

Remote verbose reports show the remote measurements and remote-computed scale
state, but omit local threshold labels because the remote host can use different
environment defaults.

For machine-readable output:

```bash
agent-thread-tools health --json
```

JSON output ignores pretty display options and is the stable scripting
interface. Legacy fields and exit behavior remain unchanged; compatible clients can
also read new state-first fields such as task lifecycle and continuation risk.

## Remote Project Health

Remote project health analyzes the session root on an SSH host. Install the
same package on both machines and verify both versions before running a report.
On the remote host the tool runs the `codex-thread-tools` command, which both
`agent-thread-tools` and the older `codex-thread-tools` package install:

```bash
npm install -g agent-thread-tools@latest
agent-thread-tools --version
ssh user@example-host codex-thread-tools --version
```

The command first looks for the remote package in non-interactive SSH. If it is
not found there, it retries through the remote account's login shell so Node
managers such as NVM work without a system-wide launcher. The command uses
normal OpenSSH configuration for authentication, including `~/.ssh/config`,
keys, agents, and host aliases. It does not require a separate credential or
token.

Run an all-project report on the SSH host:

```bash
agent-thread-tools health remote --host user@example-host
```

The remote host reports its default agent's sessions: Codex when installed there,
otherwise Claude Code. Add `--agent claude` or `--agent codex` to choose; the
remote host needs 2.0.0 or newer for that flag.

Select one project by its exact recorded path:

```bash
agent-thread-tools health remote --host user@example-host \
  --project /srv/project
```

Use verbose output with human-readable sizes:

```bash
agent-thread-tools health remote --host user@example-host \
  --mode verbose --size-format human
```

Older remote hosts continue to return legacy health output for now; upgrade agent-thread-tools to version 1.3.0 or newer to receive the state-first fields.

Use JSON for scripts or other tooling:

```bash
agent-thread-tools health remote --host user@example-host --json
```

Analysis occurs remotely against the SSH host's session root. Before
serialization, the remote process builds a privacy-safe allowlisted report
containing project identity, health status, renderer metrics, handoff state,
and canonical diagnostics. Raw session JSONL records, transcript text, tool
payloads, event or tool-error excerpts, and visual data never cross SSH. Only
package versions, the allowlisted health report, and
bounded remote stderr diagnostics cross SSH. Project matching is exact;
a path that differs by a symlink, spelling, or trailing component is not
treated as the same project.

The remote command requires privacy-safe protocol support on the SSH host. A
remote minor version without that protocol fails closed with an upgrade error;
the local command never falls back to ordinary, unsanitized health JSON. Install
the same `agent-thread-tools` version on both machines before retrying.

This command is read-only and limited to remote project health. Remote token,
archive, recovery, visual, and handoff operations are excluded.

Legacy status labels and legacy exit codes are unchanged.

### Remote Exit Codes

These are post-parse health-result codes. Invalid command syntax is handled by
`argparse`, which also returns `2` but prints a usage error instead of a health
report.

| Code | Meaning |
| --- | --- |
| `0` | The selected report contains only `OK` or `RETIRED` projects. |
| `1` | The remote operation failed, such as SSH authentication, package discovery, incompatible major versions, malformed output, or a missing project. |
| `2` | At least one selected project is `WARN`. |
| `3` | At least one selected project is `DANGER`. |

### Remote Troubleshooting

- **Host unreachable or timed out:** Confirm the host name, network route, and
  SSH service. The command uses a ten-second connection timeout by default;
  use `--connect-timeout` to adjust it.
- **Public-key rejected:** Test `ssh user@example-host` directly and fix the
  key, agent, host alias, or server account in your normal OpenSSH setup.
- **Package not found:** The tool checks both non-interactive SSH and the
  account's login shell. Confirm the package is installed for that account with
  `ssh user@example-host "bash -lc 'command -v codex-thread-tools && codex-thread-tools --version'"`.
- **Incompatible or protocol-missing versions:** Install the same version on
  both machines. A differing major version fails with exit code `1`, except that
  2.x accepts a 1.x remote with a warning (2.0.0 only renamed the package). A minor or
  patch difference is normally a warning, but a remote version without the
  privacy-safe protocol fails closed with exit code `1` instead of requesting
  ordinary health JSON.
- **Project not found:** Use the exact project path recorded on the remote
  host. Run the all-project report first and copy the path exactly into
  `--project`.

## Progress

Large screenshot-heavy sessions can take a while to parse. In an interactive
terminal, progress is printed on stderr. If your terminal or editor hides
stderr, force progress output:

```bash
agent-thread-tools health --progress always
```

## What Health Checks Inspect

Health reads both session formats the same way: Claude Code records are
translated into the Codex record shape before analysis, so every check below
applies to both agents unless it says otherwise.

- session file size
- number of response items (for Claude Code, each message and tool result)
- installed compactions: a Codex `compacted` checkpoint with
  `replacement_history`, or a Claude Code compact summary; the Claude Code
  `compact_boundary` record before each summary counts as a compaction event
- Codex only: whether the latest compacted checkpoint has `replacement_history`,
  and whether compaction signals are only requests or installed continuation state
- compaction warning or error events
- active, incomplete, aborted, and error turns
- active token usage: the latest Codex `token_count` event, when Codex persisted
  it, or the latest Claude Code reply's input, cache, and output tokens
- embedded screenshots, videos, and visual references
- whether compacted records dominate the file size

For Claude Code, a user prompt opens a turn; a `turn_duration` record or an
`end_turn` reply closes it; an interrupt aborts it; and an API error message
counts as an error.

Claude Code context use is measured against a 200,000-token window unless a reply
or compaction in the session exceeds it, in which case 1,000,000 is assumed. Set
`CLAUDE_CONTEXT_WINDOW` to fix the window size.

## Risk Domains

| Risk area | What it checks |
| --- | --- |
| `Load` | Disk size and unusually large JSONL records. |
| `Visuals` | Embedded screenshots/videos, missing visual files, and visuals inside compacted history. |
| `Compaction` | Failed, malformed, legacy, request-only, installed, or repeatedly stressed compaction state. |
| `Limits` | Response item count and active context-window pressure. |
| `Continuity` | Missing session metadata, active incomplete turns, unresolved aborted turns, or error events. |

Historical abort or error events are treated differently from unresolved ones.
If a later completed turn is persisted, the health check reports the historical
abort/error as `WARN` instead of `DANGER`. If the latest terminal event is still
an abort or error, it remains `DANGER`.

If the latest turn has no later completion, abort, or error event, the session is
reported as `WARN`. That usually means the agent was still working or the turn
did not persist a clean terminal state, so a handoff should not be treated as
clean yet.

## One Session

To check one specific session file:

```bash
agent-thread-tools health check ~/.claude/projects/<project>/<session>.jsonl
agent-thread-tools health check ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

The format is detected from the file, so `--agent` is not needed here.

## Token Usage

To estimate lifetime token usage by project:

```bash
agent-thread-tools health tokens --agent claude
agent-thread-tools health tokens --agent codex
```

You can choose the same display modes for token reports:

```bash
agent-thread-tools health tokens --mode standard
```

The token report scans session JSONL files under the selected session folder,
groups them by project, and sums the latest cumulative token total from each
token-bearing session. It also shows the latest active token estimate and active
context percentage for each project.

For Codex, the totals come from persisted `token_count` events. For Claude Code,
they are summed from each reply's input, cache, and output tokens, counted once
per message. Cache reads count on every reply, so a Claude Code total measures
how much context the session processed, not what was billed.

Use JSON when you want the per-session source records behind each project total:

```bash
agent-thread-tools health tokens --json
```

Treat this as a session-scale report, not a billing ledger. Older Codex sessions
may not contain `token_count` events, and missing token data is reported as
`not recorded` rather than guessed as zero.
