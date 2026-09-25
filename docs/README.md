# agent-thread-tools Documentation

This documentation is the detailed reference for `agent-thread-tools`, which
works with Claude Code and Codex sessions.

Start with the root [README](../README.md) if you only need the quick path.
Use the pages below when you want the exact command flow, safety model, or
release process.

## User Guides

| Topic | Use this when |
| --- | --- |
| [Installation](installation.md) | You want to install the tools or a handoff skill, from a terminal or from inside a Claude Code app. |
| [Claude Code](claude-code.md) | You use Claude Code and want the details: where sessions live, what health measures, `/thread-handoff`, and how handoffs link sessions. |
| [Thread health](health.md) | You want local or SSH-host project reports, report modes, risk domains, and token reports. |
| [Handoff workflow](handoff.md) | You want to preserve durable project context and continue in a fresh session. |
| [Session archive](session-archive.md) | You want staged, verified cold storage and recoverable local pruning for old Claude Code and Codex sessions. |
| [Visual archive](visual-archive.md) | You want verified copies of screenshots and videos outside an oversized session. |
| [Recovery](recovery.md) | You need a safe diagnosis, a repair, or an external recovery bundle for a damaged or oversized session. |
| [Compaction](compaction.md) | You want to understand how compaction differs from handoffs and archives. |

## Maintainer Guides

| Topic | Use this when |
| --- | --- |
| [Changelog](../CHANGELOG.md) | You want the release-by-release history of changes. |
| [Development](development.md) | You are editing this repository, running tests, or checking package contents. |
| [Publishing](publishing.md) | You are preparing a GitHub release that publishes to npm through Trusted Publishing. |
