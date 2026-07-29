# Changelog

## Unreleased

## 1.3.1 - 2026-07-29

- Restore explicit health severity in project reports and use monitor guidance
  for warning-level continuation risk.
- Treat successful compaction counts as scale information and restrict prompt
  handoff markers to user-authored messages.

## 1.3.0 - 2026-07-27

- Add state-first health reporting with explicit task lifecycle state and continuation
  risk for local and remote projects.
- Add remote protocol 1 state validation so compatible hosts include additive state
  fields while older remote reports remain accepted.
- Clarify action semantics so active safe turns are finished, watch states trigger
  deliberate handoff prep, and danger states require handoff before continuing.
- Distinguish request-only compaction records from installed checkpoints when
  calculating scale and continuation risk.
- Show measured size, response items, installed checkpoints, visuals, and effective
  thresholds in standard single-session reports.
- Fail closed on malformed remote notice values and preserve marker source identity
  when retirement is matched by session-file path.
- Keep legacy JSON payload fields and exit codes unchanged.

## 1.2.0 - 2026-07-18

- Add structural detection for malformed or remote model-visible image URLs,
  including replayable custom/function tool outputs and image values retained
  inside compacted replacement history.
- Add `recover diagnose` for read-only integrity reports and `recover bundle`
  for staged, external, redacted recovery artifacts that leave the source JSONL
  unchanged.
- Include integrity counts in local health and privacy-safe remote health
  reports, while retaining compatibility with older remote report schemas.
- Stream integrity analysis through health checks instead of reopening a large
  session for a second structural scan.
- Restore the linked Medium article in the README, which npm renders on the
  package page.

## 1.1.2 - 2026-07-15

- Restore visible changelog links in the root README and documentation index.
- Update the npm publishing workflow to `actions/setup-python@v6` for the
  supported Node 24 GitHub Actions runtime.
- Restore Python 3.9 compatibility for the remote-health test module.
- Keep a successfully installed archive live when only cleanup of its prior
  backup fails, and retain that backup for recovery.
- Report validation-aborted prune entries as restored when rollback succeeds.
- Use buffered I/O consistently when initializing archive reservation files.
- Restore a session to its original path after a quarantined delete failure when
  that path is still free; otherwise retain an explicit recovery file.

## 1.1.1 - 2026-07-14

- Expand best-effort handoff-summary redaction for common credentials, authorization headers, private keys, and credential-bearing URLs.
- Replace raw health-event snippets with canonical diagnostics so local JSON reports do not preserve session text.
- Confine archive verification to manifest-owned directories and reject traversal and symlink escapes.
- Use staged, transactional session and visual archive replacement so stale files
  are removed only after the replacement is ready and handled failures preserve
  the prior archive; crash consistency is not guaranteed.
- Preflight local session pruning and verify staged archive copies before replacing
  existing archives.
- Serialize archive replacement and pruning with persistent operating-system
  advisory locks that cannot be reclaimed from an active process using stale metadata.
- Stage session pruning in same-filesystem recovery quarantine, fail closed on
  malformed visual manifests, and report expected integrity failures without
  tracebacks. Cleanup failures and process or OS crashes are not guaranteed to
  restore prior archive state.
- Harden SSH destination validation and consolidate shared parsing, hashing, timestamp, and archive naming helpers without changing CLI syntax.

## 1.1.0 - 2026-07-13

- Add `codex-thread-tools health remote --host <ssh-host>` for health reports
  generated on a remote Codex host without copying session JSONL files locally.
- Support exact project selection, existing display modes and thresholds, JSON
  output, version compatibility checks, and actionable SSH diagnostics.
- Retry remote commands through the account's login shell when needed so
  NVM-managed installations work without system-wide launchers or PATH changes.
- Prefer user-owned root sessions over newer subagent and automation files in
  both local and remote project health reports.

## 1.0.0 - 2026-06-27

- Mark the CLI surface as production-ready and move the package version to
  `1.0.0`.
- Trim the root README into a concise project landing page and move detailed
  usage into an indexed public `docs/` section.
- Add `codex-thread-tools session-archive` with `plan`, `archive`, `verify`,
  and guarded `prune-local` phases for moving old session JSONL files to
  external storage.
- Write verifiable session archive manifests with source paths, archive paths,
  byte counts, timestamps, session IDs, and SHA-256 hashes.
- Wire session archive support through the npm CLI and package metadata.

## 0.4.8 - 2026-06-26

- Add active-turn and incomplete-turn safety checks so health reports do not
  treat an in-progress turn as clean handoff state.
- Distinguish compaction request items from installed replacement-history
  checkpoints in health metrics.
- Add `codex-thread-tools handoff-summary` for read-only, redacted handoff
  summary drafts that preserve concise durable context without copying raw tool
  payloads.

## 0.4.7 - 2026-06-26

- Clarify the difference between Codex remote host handoff and this repo's
  repo-backed `codex-thread-handoff` continuity workflow.

## 0.4.6 - 2026-06-11

- Improve `codex-thread-tools health` and `health tokens` human output with
  table-first display modes, readable standard-mode action summaries, and
  human-readable size formatting.
- Add a GitHub Actions workflow for release-gated npm Trusted Publishing with
  version checks, tests, latest npm CLI setup, dry-run packaging, and npm
  provenance.
- Add package author metadata for Rich Olson.
- Improve README command guidance so `npx`, global npm install, and source
  checkout workflows are all documented clearly.
- Reformat README sections with GitHub-supported tables, alerts, a Mermaid
  workflow diagram, and collapsed source-only details for easier scanning.
- Fix the npm CLI wrapper so a command runs with only the first available
  Python interpreter instead of running once per detected interpreter.
- Clarify the npm package description shown in npm search and package listings.

## 0.4.5 - 2026-06-05

- Prepare the project for npm publishing as `codex-thread-tools`.
- Add the `codex-thread-tools` npm CLI wrapper for health checks, handoff markers, visual archives, recovery, and skill installation.
- Document `npx codex-thread-tools health` and `npm install -g codex-thread-tools` usage.
- Add package metadata and packaging tests for npm publish readiness.

## 0.4.4 - 2026-06-05

- Remove the macOS app-path assumption from Codex process detection.
- Read the package version from `VERSION` and point security policy version text at the same file.
- Add README header artwork and clarify the target Codex app.
- Polish README prose and simplify Codex naming after the first OpenAI Codex mention.

## 0.4.3 - 2026-06-03

- Report sidecar-marked source sessions as top-level `RETIRED` instead of active `WARN` or `DANGER`.
- Keep retired source session diagnostics as underlying health while returning a successful exit code.
- Allow sidecar markers to record replacement session files for older handoffs that lack prompt markers.
- Clarify that older handoffs can be backfilled with a local sidecar marker without editing Codex session JSONL.

## 0.4.2 - 2026-06-03

- Add local sidecar handoff markers and prompt markers for connecting replacement threads to retired source sessions.
- Make project health reports prefer the active replacement thread over retired source sessions.
- Report per-project handoff totals in health output.

## 0.4.1 - 2026-06-03

- Downgrade historical turn abort/error events from `DANGER` to `WARN` when a later persisted completion event shows the thread recovered.
- Keep unresolved latest turn abort/error events as `DANGER`.
- Add separate continuation health and handoff readiness fields to thread health reports.
- Treat opaque compaction items as normal continuation state unless persisted failure events or malformed local compacted records are present.
- Require explicit visual archive decisions in handoff guidance when visual references exist.
- Move detailed handoff workflow instructions into a deferred reference file to reduce the active skill prompt.

## 0.4.0 - 2026-05-28

- Rename and reposition the project as `codex-thread-tools`.
- Rename the internal Python package to `codex_thread_tools`.
- Keep the repository focused on Codex thread health, visual archiving, handoff, and recovery.
- Remove unrelated general-purpose skills from the public tracked tree.

## 0.3.0 - 2026-05-28

- Add `codex-visual-archive.py` for read-only visual scans, external visual archive creation, and archive verification.
- Add the `Visuals` health domain to `codex-thread-health.py`.
- Add lightweight embedded-media sizing so health checks do not hash or copy large visual payloads.
- Add project lifetime token reporting with `codex-thread-health.py tokens`.
- Add generated visual fixtures and test coverage without committing machine-local generated artifacts.
- Remove local usage artifacts from the public repository tree and ignore future private handoff and archive outputs.

## 0.2.0 - 2026-05-26

- Add domain-based thread health reporting for load, compaction, limits, and continuity risk.
- Add safer Codex thread handoff guidance.
- Add fixture-backed tests for Codex session health analysis.

## 0.1.0 - 2026-05-18

- Initial `codex-thread-handoff` skill.
- Initial recovery starter tooling for oversized Codex session JSONL files.
