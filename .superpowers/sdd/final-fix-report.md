# Final Whole-Branch Fix Report

Status: DONE

Branch: `codex/remote-thread-health`

Remote hosts were not contacted or modified. Nothing was published or pushed.
`VERSION`, `package.json`, and other release metadata were not changed.

## Findings Fixed

1. Remote-safe replacement IDs now accept only canonical hyphenated Codex UUIDs.
   Lowercase and uppercase hex are accepted. The same predicate is used by the
   remote-safe builder and local report validation. Identifier-like transcript
   text is omitted from remote output while local JSON remains unchanged.
2. OpenSSH `ConnectTimeout` remains on both SSH commands. Only the quick version
   probe has a Python subprocess wall timeout; remote health analysis has none.
   Timeout errors identify the version probe rather than claiming connection
   establishment timed out.
3. Remote report summaries are recomputed from validated project statuses and
   must match all `projects/ok/warn/danger/retired` counters. A mismatch is a
   protocol error, and the CLI exits `1` without report output.
4. Health transport documentation now states that bounded remote stderr
   diagnostics also cross SSH.
5. `health remote` no longer exposes or accepts `--progress` or
   `--handoff-marker-file`. Local `check`, `projects`, and `tokens` retain both.
6. Immutability coverage now proves selected and unfiltered project selection
   leave inputs unchanged, and metadata addition leaves both `source` and
   `host` absent from the input.

## TDD Evidence

### Replacement ID Privacy And Immutability

RED:

```text
.venv/bin/python -m pytest tests/test_remote_health.py tests/test_thread_health.py -k 'canonical_codex_session_ids or non_uuid_replacement_id or remote_safe_projects_protocol or select_remote_project or add_remote_metadata' -vv
```

Result: `3 failed, 6 passed, 98 deselected`. The builder retained the arbitrary
marker-shaped ID, validation accepted it, and the end-to-end remote-safe report
serialized the transcript sentinel. The four immutability assertions passed
before production changes, confirming those were coverage-only additions.

GREEN: the same command returned `9 passed, 98 deselected`.

### SSH Timeout Separation

RED:

```text
.venv/bin/python -m pytest tests/test_remote_health.py::test_run_remote_health_probes_version_and_returns_report tests/test_remote_health.py::test_run_remote_health_maps_ssh_timeout -vv
```

Result: `4 failed`. All three health return-code cases still received
`timeout=12`, and the timeout error still said the SSH connection timed out.

GREEN: the same command returned `4 passed`. The version probe receives the
12-second wall timeout for `connect_timeout=7`; the analysis call has no
`timeout` keyword.

### Summary Consistency

RED:

```text
.venv/bin/python -m pytest tests/test_remote_health.py::test_validate_projects_report_rejects_summary_that_disagrees_with_projects tests/test_thread_health.py::test_remote_danger_with_zeroed_summary_is_protocol_error -vv
```

Result: `2 failed`. Validation accepted the mismatch, and a danger project with
a zeroed summary produced CLI exit `0` and JSON output.

GREEN: the same command returned `2 passed`. The mismatch is rejected and the
CLI returns `1` with empty stdout.

### Parser Surface And Documentation

RED:

```text
.venv/bin/python -m pytest tests/test_thread_health.py::test_remote_help_exposes_connection_and_report_options tests/test_thread_health.py::test_local_health_help_preserves_scan_options tests/test_thread_health.py::test_remote_rejects_local_scan_options tests/test_docs.py::test_health_docs_cover_remote_health_contract -vv
```

Result: `4 failed, 3 passed`. Remote help exposed both unsupported options,
remote parsing accepted both, and the transport wording was absent. All three
local help cases already exposed the required options.

GREEN: the same command returned `7 passed`.

## Verification

Focused suites:

```text
.venv/bin/python -m pytest tests/test_remote_health.py tests/test_thread_health.py tests/test_docs.py
```

Result: `119 passed in 11.72s`.

The first focused run found one invalid pre-existing test fixture that appended
an uncounted project after summary validation became strict: `1 failed, 118
passed`. The test now replaces an existing project identity, preserving its SSH
injection purpose while keeping the protocol payload valid.

Full suite:

```text
.venv/bin/python -m pytest
```

Result: `168 passed in 15.14s`.

The first full run found only a docs assertion split by line wrapping: `1
failed, 167 passed`. Moving the wrap boundary restored the exact required
phrase; the focused docs test then passed and the full suite passed on rerun.

Whitespace:

```text
git diff --check
```

Result: exit `0`, no output.

Package dry-run:

```text
npm_config_cache=/private/tmp/codex-thread-tools-npm-cache npm pack --dry-run --json
```

Result: exit `0`; package `codex-thread-tools@1.1.0`, filename
`codex-thread-tools-1.1.0.tgz`, 39 entries, no bundled dependencies.

## Files

- `codex_thread_tools/remote_health.py`
- `tools/codex-thread-health.py`
- `tests/test_remote_health.py`
- `tests/test_thread_health.py`
- `docs/health.md`
- `tests/test_docs.py`
- `.superpowers/sdd/final-fix-report.md`

## Self-Review

- Privacy filtering and validation use one canonical UUID predicate; no error
  includes rejected replacement content.
- The marker-shaped transcript regression proves the sentinel appears in local
  `replaces_session_ids` but not remote stdout or stderr.
- Summary comparison occurs only after every project entry is validated.
- Project selection reuses the same summary derivation helper.
- Remote analysis has no Python wall timeout, while OpenSSH connection timeout
  arguments remain intact.
- Local JSON construction and all compact/standard/verbose render paths were
  left unchanged and are covered by the focused and full suites.
- No unrelated files or release metadata were changed.

## Concerns

Legacy non-UUID replacement IDs are intentionally omitted only from remote-safe
reports under the new privacy contract. They remain unchanged in local JSON.
No live remote integration was run because remote access and host modification
were explicitly excluded.
