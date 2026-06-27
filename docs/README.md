# codex-thread-tools Documentation

This documentation is the detailed reference for `codex-thread-tools`.

Start with the root [README](../README.md) if you only need the quick path.
Use the pages below when you want the exact command flow, safety model, or
release process.

## User Guides

| Topic | Use this when |
| --- | --- |
| [Installation](installation.md) | You want to choose between `npx`, global npm install, or source checkout. |
| [Thread health](health.md) | You want to understand `codex-thread-tools health`, report modes, risk domains, and token reports. |
| [Handoff workflow](handoff.md) | You want to preserve durable project context and rotate into a fresh Codex thread. |
| [Session archive](session-archive.md) | You want to move old session JSONL files to external storage and optionally prune local copies. |
| [Visual archive](visual-archive.md) | You want to preserve screenshots and videos outside an oversized Codex thread. |
| [Recovery](recovery.md) | You need to inspect or back up a damaged or oversized session file. |
| [Compaction](compaction.md) | You want to understand how Codex compaction differs from handoffs and archives. |

## Maintainer Guides

| Topic | Use this when |
| --- | --- |
| [Development](development.md) | You are editing this repository, running tests, or checking package contents. |
| [Publishing](publishing.md) | You are preparing a GitHub release that publishes to npm through Trusted Publishing. |
