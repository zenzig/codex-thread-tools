<div align="center">

# agent-thread-tools

**Your Codex or Claude Code session is a black box that only gets heavier. This is the toolkit that opens it up.**

[![npm version](https://img.shields.io/npm/v/agent-thread-tools.svg)](https://www.npmjs.com/package/agent-thread-tools)
[![npm downloads](https://img.shields.io/npm/dm/agent-thread-tools.svg)](https://www.npmjs.com/package/agent-thread-tools)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Documentation](https://img.shields.io/badge/docs-project_guides-brightgreen.svg)](docs/README.md)

<img src="assets/agent-thread-tools-header.png" alt="A tangled Codex thread being organized onto a spool" width="100%">

</div>

Formerly `codex-thread-tools`. The old command name still works as an alias.

## The problem

Every long Codex task ends the same way: a JSONL file on disk quietly ballooning with compacted history, tool output, screenshots, and thousands of response items — until it's too heavy to load, too risky to trust, and too big to read to figure out what's even in it.

Compaction trims what Codex keeps *in context*. It does nothing for the file sitting on disk, and it doesn't leave you anything durable to carry into a fresh task. So you're stuck choosing between grinding forward in a degraded session or starting over and losing everything you'd learned.

`agent-thread-tools` is the toolkit for that moment in between: spot the risk before it bites, pull out what's actually worth keeping, and get the rest out of your way — without ever treating raw transcripts as documentation.

Read the background: [The Thread That Ate Itself: What Happens When Your Codex Session Gets Too Big to Open](https://medium.com/@atomicfalls/the-thread-that-ate-itself-what-happens-when-your-codex-session-gets-too-big-to-open-5ee559f263f3).

## Use it when you want to

- Know whether a task — local or remote — is still healthy enough to keep pushing.
- Get a straight answer: keep going, keep watching, or hand off.
- Carry the decisions and screenshots that matter into a clean task.
- Archive stale sessions with manifests and integrity checks, not just `rm`.
- Recover something useful from a session that's already too big or broken to open.

## What's in the box

| Capability | Purpose |
| --- | --- |
| Thread health | Scores load, compaction, context limits, continuity, and visual risks. |
| Remote health | Same analysis over SSH — without shipping raw session files anywhere. |
| Handoff workflow | Preserves the concise project facts a fresh task actually needs. |
| Handoff summaries | Redacted drafts — no raw tool payloads along for the ride. |
| Session archives | Moves old JSONL files into staged, verified archives, with a recovery quarantine before local pruning. |
| Visual archives | Keeps referenced screenshots and videos alive outside task history. |
| Recovery | Diagnoses unsafe replay inputs and creates redacted, external recovery bundles. |

Everything defaults to read-only. Anything that copies or prunes files needs an explicit command, a verification step, and a confirmation flag — nothing destructive happens by accident.

## Quick start

Try it with no install:

```bash
npx agent-thread-tools health
```

Living with it day to day:

```bash
npm install -g agent-thread-tools
agent-thread-tools health
```

(The npm package wraps bundled Python tools — you'll need Node.js 18+ and Python 3 on `PATH`.)

Want Codex to prepare a handoff when you ask? Install the skill:

```bash
agent-thread-tools install-skill
```

When the active task needs rotation, use this exact request from any Codex thread:

```text
Use the installed `codex-thread-handoff` skill to create a repository-backed
handoff for a new task. Do not use Codex's native Handoff or `handoff_thread`.
If the skill is unavailable, stop and report that it must be installed.
```

## Claude Code

The same health checks, handoff summaries, and visual archives work on Claude Code
sessions (`~/.claude/projects/<project>/<session>.jsonl`). The format is detected per
file; subagent transcripts are skipped when scanning.

```bash
agent-thread-tools health --agent claude          # every Claude Code project
agent-thread-tools install-skill --agent claude   # adds /thread-handoff
```

In Claude Code, run `/thread-handoff` when health says to, then `/clear`. The handoff
is wired into `CLAUDE.local.md`, so the fresh session starts with it loaded. See
[Claude Code](docs/claude-code.md).

## How it works

1. **Inspect** — a health report selects one project session and scores independent risk domains, not just raw file size.
2. **Decide** — it tells you plainly: continue, monitor, or hand off, and shows the signals behind that call.
3. **Preserve** — handoff and archive tools keep the durable facts and visual evidence, and leave the bulky or sensitive payloads behind.
4. **Continue** — start clean with tight project context, while the old session stays around for recovery or verified archiving.

### Local health

```bash
agent-thread-tools health
agent-thread-tools health --mode standard
agent-thread-tools health --mode verbose --size-format both
agent-thread-tools health --json
```

The human-readable output is for your terminal. `--json` is the stable interface if you're scripting against it.
Health separates the latest turn from continuation risk. `WARN` means monitor the selected session; `DANGER` is what triggers handoff-now guidance. Successful compaction counts remain visible as scale information without requiring a handoff by themselves.
`--json` keeps existing machine-readable compatibility fields and adds state-first fields for compatible clients.

### Remote health

Install the same package on both ends, then:

```bash
agent-thread-tools health remote --host user@example-host \
  --project /srv/project
```

The analysis runs on the remote host. Only a privacy-filtered report and bounded diagnostics ever cross SSH — raw JSONL, transcript text, tool payloads, and visual data never leave the remote machine. If the CLI isn't reachable over a non-interactive SSH session, it automatically retries through your login shell, NVM installs included.

## Documentation

Start at [Documentation](docs/README.md), or jump straight to:

| Guide | Topic |
| --- | --- |
| [Installation](docs/installation.md) | `npx`, global npm, source, and skill installation. |
| [Thread health](docs/health.md) | Local/remote reports, risk domains, output modes, exit codes. |
| [Handoff workflow](docs/handoff.md) | Durable context, summaries, markers, remote-handoff distinctions. |
| [Session archive](docs/session-archive.md) | Staged archive, verification, recovery, and prune workflows. |
| [Visual archive](docs/visual-archive.md) | Screenshot and video preservation. |
| [Recovery](docs/recovery.md) | Safe diagnosis and external bundles for damaged sessions. |
| [Compaction](docs/compaction.md) | Compaction, handoff, and archive boundaries. |

## Project

- **Status:** Production
- **Version:** `2.0.0`
- **Issues:** [Report a bug or request a feature](https://github.com/zenzig/agent-thread-tools/issues)
- **Security:** Read the [security policy](SECURITY.md) before reporting a vulnerability.
- **[Changelog](CHANGELOG.md):** Release history and notable changes.
- **Development:** See the [development guide](docs/development.md) for tests and package checks.
- **License:** [MIT](LICENSE)
