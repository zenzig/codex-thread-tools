# Changelog

## Unreleased

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
