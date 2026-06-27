<div align="center">

# codex-thread-tools

**Production-ready CLI tools and a Codex skill for keeping long OpenAI Codex threads healthy.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0.0-blue)](CHANGELOG.md)
[![Docs](https://img.shields.io/badge/docs-index-brightgreen)](docs/README.md)
[![Tests](https://img.shields.io/badge/tests-pytest-brightgreen)](docs/development.md)

<img src="assets/codex-thread-tools-header.png" alt="codex-thread-tools turns tangled Codex session threads into an organized spool" width="100%">

</div>

---

## What This Is

Current version: `1.0.0`

`codex-thread-tools` works with local Codex session JSONL files under
`~/.codex/sessions/`.

Codex compaction helps long conversations continue, but it does not make an
oversized local thread a good place to keep all project memory. This repo gives
you practical tools for checking thread health, preserving durable context,
archiving old session data, and recovering from oversized-session problems.

The `1.0.0` release marks the CLI surface as production-ready. Stable scripting
should use `--json`; human-readable output may keep improving over time.

## Quick Start

Run once with `npx`:

```bash
npx codex-thread-tools health
```

Install globally:

```bash
npm install -g codex-thread-tools
codex-thread-tools health
```

Install the bundled handoff skill:

```bash
codex-thread-tools install-skill
```

Then, from any Codex thread:

```text
Use codex-thread-handoff.
```

Python 3 must be available on your `PATH`. The npm package is a wrapper around
the bundled Python tools.

## Tools

| Tool | What it does | Main command |
| --- | --- | --- |
| Health check | Reports whether Codex project threads look ok, risky, or ready for handoff. | `codex-thread-tools health` |
| Handoff summary | Creates a concise, redacted summary draft from one session file. | `codex-thread-tools handoff-summary <session.jsonl>` |
| Session archive | Copies old session JSONL files to external storage with verifiable manifests. | `codex-thread-tools session-archive` |
| Visual archive | Copies screenshots and videos out of old threads into storage you choose. | `codex-thread-tools visual-archive` |
| Handoff skill | Writes durable project context before starting a fresh Codex thread. | `codex-thread-tools install-skill` |
| Recovery starter | Helps inspect and back up damaged or oversized session files. | `codex-thread-tools recover` |

## Documentation

Read the [Documentation](docs/README.md) index for full command usage and
maintainer notes.

| Guide | Covers |
| --- | --- |
| [Installation](docs/installation.md) | `npx`, global npm install, source checkout, and skill install. |
| [Thread health](docs/health.md) | Health reports, display modes, risk domains, token reports, and JSON output. |
| [Handoff workflow](docs/handoff.md) | Repo-backed continuity, redacted summaries, and handoff markers. |
| [Session archive](docs/session-archive.md) | Moving old JSONL sessions to external storage and pruning verified local copies. |
| [Visual archive](docs/visual-archive.md) | Preserving screenshots and videos outside oversized threads. |
| [Recovery](docs/recovery.md) | Inspecting and backing up damaged sessions. |
| [Compaction](docs/compaction.md) | How Codex compaction differs from handoffs and archives. |
| [Development](docs/development.md) | Tests, fixtures, package checks, and repo hygiene. |
| [Publishing](docs/publishing.md) | GitHub release and npm Trusted Publishing flow. |

## Command Reference

| Task | Command |
| --- | --- |
| Project health report | `codex-thread-tools health` |
| One session health report | `codex-thread-tools health check <session.jsonl>` |
| Token usage report | `codex-thread-tools health tokens` |
| Redacted handoff summary draft | `codex-thread-tools handoff-summary <session.jsonl>` |
| Record handoff marker | `codex-thread-tools handoff-marker record ...` |
| Plan old session archive | `codex-thread-tools session-archive plan ...` |
| Archive old session files | `codex-thread-tools session-archive archive ...` |
| Verify session archive | `codex-thread-tools session-archive verify --manifest <manifest.json>` |
| Prune archived local sessions | `codex-thread-tools session-archive prune-local --manifest <manifest.json> --confirm-prune-local` |
| Scan visual references | `codex-thread-tools visual-archive scan <session.jsonl>` |
| Archive visual references | `codex-thread-tools visual-archive archive <session.jsonl> ...` |
| Inspect a damaged thread | `codex-thread-tools recover inspect <session.jsonl>` |

## The Simple Rule

Use compaction to keep working inside the current thread.

Use a handoff when the thread is getting large, has compacted several times, or
contains decisions that should survive outside the chat log.

Use archive tools when old sessions or visuals should be preserved somewhere
other than your live Codex session folder.

Use recovery tools only after a thread is already hard to load, has disappeared
from the sidebar, or has hit a compaction/context error.

## License

MIT. See [LICENSE](LICENSE).
