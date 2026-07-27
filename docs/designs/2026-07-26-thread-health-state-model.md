# Thread Health State Model Design

## Goal

Make `codex-thread-tools health` describe the current state of a Codex task
without conflating an in-progress turn, continuation safety, completed-handoff
lineage, and historical visual evidence into one `WARN` label.

The first delivery adds explicit, privacy-safe state axes to local and remote
JSON reports and makes human-readable output state-first. It does not add a
historical snapshot store or change existing JSON fields, CLI options, or exit
codes.

## Problem

The current health decision aggregates every risk domain into one legacy
`status`. `handoff_readiness()` then maps every legacy `warn` result to
`recommended`. Consequently, a new task can be labelled `WARN` and
`Handoff: Recommended` only because it has an unmatched `turn_started` event
or historical visual references inside compacted records. Those signals matter
for diagnosis, but neither independently means that the active task should be
replaced.

## Compatibility

Existing fields remain unchanged:

- `status`, `continuation_status`, `recommendation`, `overall_assessment`
- `reasons` and `risk_domains`
- `handoff_readiness`, `handoff_summary`, `replaces_session_ids`, and
  `retired_by_handoff`
- CLI syntax, JSON exit codes, and the remote health protocol version

The new JSON fields are additive. Existing scripts can keep consuming the
legacy fields while new clients can use the separated axes. Exit code `0`, `2`,
or `3` remains driven by the legacy aggregate status for this release.

## State Axes

Every single-session and project result gains the following fields.

### Task State

```json
{
  "task_state": {
    "status": "active",
    "reason": "latest recorded turn has no terminal event"
  }
}
```

Allowed values are:

- `active`: one or more turn-start events do not yet have a terminal event.
- `completed`: the latest tracked turn ended with `turn_complete`.
- `interrupted`: the latest tracked turn ended with `turn_aborted` or `error`.
- `unknown`: event data cannot establish a current turn state.

`active` is a lifecycle state. It must not, by itself, make continuation risk
`watch`, recommend a handoff, or change action from `continue` to
`prepare-handoff`.

### Continuation Risk

```json
{
  "continuation_risk": {
    "status": "ok",
    "reasons": []
  }
}
```

Allowed values are `ok`, `watch`, and `danger`.

- `danger`: replay-integrity failures, unrecovered turn failures, dangerous
  size or token pressure, compaction failure, or another existing danger-level
  continuity, load, visual, compaction, or limits condition.
- `watch`: warning-level scale, token, compaction, integrity, or unrecovered
  continuity conditions that make a deliberate future handoff prudent.
- `ok`: no condition requiring a near-term handoff.

An unmatched active turn is represented only in `task_state`. Historical visual
references inside compacted records are notices unless another integrity or
scale rule independently makes them a continuation risk.

### Handoff Lineage

```json
{
  "handoff_lineage": {
    "status": "replacement-active",
    "source_session_ids": ["019f47ef-8568-7300-9e7c-59c81c9ccdcf"],
    "total_handoffs": 1
  }
}
```

Allowed values are:

- `not-recorded`: no sidecar or prompt-marker lineage is known.
- `replacement-active`: this session replaces one or more marked source
  sessions.
- `source-retired`: this session was retired by a completed handoff.
- `incomplete`: source/replacement evidence exists but the marker state is not
  sufficient to establish a completed lineage.

The report must not infer a missing sidecar merely because a task is new. It
uses `incomplete` only when actual partial marker evidence exists.

### Scale

```json
{
  "scale": {
    "status": "ok",
    "size": "ok",
    "items": "ok",
    "compactions": "ok",
    "visuals": "notice"
  }
}
```

`scale` reports current threshold position, not a growth rate. The tool does
not persist historical snapshots in this release, so it must not imply a trend
or estimate time to a threshold.

### Action

```json
{
  "action": {
    "status": "finish-current-turn",
    "reason": "task is active; no continuation risk requires a handoff"
  }
}
```

Allowed values are `continue`, `finish-current-turn`, `prepare-handoff`,
`handoff-now`, and `use-replacement`.

Action precedence is:

1. A retired source uses `use-replacement`.
2. Danger continuation risk uses `handoff-now`.
3. Watch continuation risk uses `prepare-handoff`.
4. Active task state with `ok` continuation risk uses `finish-current-turn`.
5. Otherwise use `continue`.

## Rendering

`standard` output leads with the state axes, then scale and notices:

```text
Current State
Task: Active - latest turn has no terminal event
Continuation: OK
Handoff: Replacement active
Action: Finish the current turn, then continue.

Scale
Size: 13.1 MiB of 512 MiB warning threshold
Items: 2,548 of 8,000 warning threshold
Compactions: 5
Visuals: 59

Notices
- Visual references exist inside compacted replacement history.
```

`projects` uses columns for task state, continuation risk, handoff lineage,
action, and compact scale. `compact` remains one screen. `verbose` adds the
full domain table, terminal-event counts, lineage identifiers, paths, reasons,
and legacy aggregate status.

Legacy `status` remains visible in verbose diagnostics and JSON but does not
lead the standard human report.

## Remote Health And Privacy

The remote-safe report includes the additive state fields with only allowlisted
enums, canonical diagnostics, counts, and canonical session IDs. It must not
send transcript content, tool payloads, arbitrary paths beyond the existing
project/file identity, or marker-file contents.

Older remote hosts remain supported. The local client treats absent additive
fields as unknown/unavailable for display instead of failing report validation.

## Verification

Add focused coverage for:

- active but otherwise safe task: `task_state=active`,
  `continuation_risk=ok`, `action=finish-current-turn`, and no handoff
  recommendation;
- historical compacted visual references only: a notice, not continuation
  risk;
- scale, token, or compaction pressure: `continuation_risk=watch` and
  `action=prepare-handoff`;
- replay-integrity or unrecovered failure: `continuation_risk=danger` and
  `action=handoff-now`;
- marker-backed replacement and retired source lineage;
- local JSON compatibility, legacy exit codes, and remote privacy validation;
- compact, standard, and verbose report semantics.

Update `README.md` and `docs/health.md` to explain that task activity and
continuation risk are separate, and to show active, watch, danger, and retired
examples.

## Out Of Scope

- Historical health snapshot storage, growth-rate calculations, and scheduled
  trend collection.
- Changes to the session JSONL format.
- Automatic handoffs or task-management actions.
- A breaking remote protocol or JSON schema change.
