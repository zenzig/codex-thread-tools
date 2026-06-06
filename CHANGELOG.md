# Changelog

## Unreleased

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
- Remove local usage artifacts from the public repository tree and ignore future `docs/`, handoff, and archive outputs.

## 0.2.0 - 2026-05-26

- Add domain-based thread health reporting for load, compaction, limits, and continuity risk.
- Add safer Codex thread handoff guidance.
- Add fixture-backed tests for Codex session health analysis.

## 0.1.0 - 2026-05-18

- Initial `codex-thread-handoff` skill.
- Initial recovery starter tooling for oversized Codex session JSONL files.
