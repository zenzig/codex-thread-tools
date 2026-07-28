# Thread Health

The main command is:

```bash
codex-thread-tools health
```

It scans your Codex session folder, finds the active user-owned root session
for each project, and reports whether each thread looks safe to continue. A
newer subagent or automation session does not replace that root in the project
report. If a project has no root session, the newest available child session is
used as a fallback.

## Statuses

| Status | Meaning | What to do |
| --- | --- | --- |
| `OK` | No major risk signals were found. | Keep working. |
| `WARN` | One risk area needs attention. | Finish the current turn; then continue with increased scrutiny or a deliberate handoff. |
| `DANGER` | Strong risk signals were found. | Handoff before continuing. |
| `RETIRED` | The session was already handed off and is no longer active. | Use the replacement thread or the handoff file. |

Task state and continuation risk are separate. Health separates task lifecycle
state from continuation risk. A thread can be in an
active turn and still be safe to finish; handoff guidance is based on whether
continuation risk is low, rising, or high.

| Task State | Continuation Risk | Handoff Lineage | Action |
| --- | --- | --- | --- |
| `active` | `ok` | Any | Finish the current turn, then continue. |
| `active` | `watch` | Any | Finish the current turn and prepare a deliberate handoff. |
| `active` | `danger` | Any | Handoff before continuing. |
| Any | Any | `source-retired` | Use the replacement thread or handoff summary. |

For historical compacted visual references, the report emits notice-level output by
themselves so they can be reviewed without being treated as unsafe continuity
signals.

The health check is read-only. It does not edit, delete, trim, or repair any
Codex thread.

## Display Modes

The default human report is table-first and uses exact byte counts.

Compact dashboard:

```bash
codex-thread-tools health --mode compact
```

Standard table output:

```bash
codex-thread-tools health --mode standard
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
interface. Legacy fields and exit behavior remain unchanged; compatible clients can
also read new state-first fields such as task lifecycle and continuation risk.

## Remote Project Health

Remote project health analyzes the session root on an SSH host. Install the
same package on both machines and verify both versions before running a report:

```bash
npm install -g codex-thread-tools@latest
codex-thread-tools --version
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
codex-thread-tools health remote --host user@example-host
```

Select one project by its exact recorded path:

```bash
codex-thread-tools health remote --host user@example-host \
  --project /srv/project
```

Use verbose output with human-readable sizes:

```bash
codex-thread-tools health remote --host user@example-host \
  --mode verbose --size-format human
```

Older remote hosts continue to return legacy health output for now; upgrade codex-thread-tools to version 1.3.0 or newer to receive the state-first fields.

Use JSON for scripts or other tooling:

```bash
codex-thread-tools health remote --host user@example-host --json
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
the same `codex-thread-tools` version on both machines before retrying.

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
  both machines. A differing major version fails with exit code `1`. A minor or
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
