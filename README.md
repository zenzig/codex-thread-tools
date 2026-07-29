<div align="center">

# codex-thread-tools

**Your Codex session is a black box that only gets heavier. This is the toolkit that opens it up.**

[![npm version](https://img.shields.io/npm/v/codex-thread-tools.svg)](https://www.npmjs.com/package/codex-thread-tools)
[![npm downloads](https://img.shields.io/npm/dm/codex-thread-tools.svg)](https://www.npmjs.com/package/codex-thread-tools)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Documentation](https://img.shields.io/badge/docs-project_guides-brightgreen.svg)](docs/README.md)

<img src="assets/codex-thread-tools-header.png" alt="A tangled Codex thread being organized onto a spool" width="100%">

</div>

## The problem

Every long Codex task ends the same way: a JSONL file on disk quietly ballooning with compacted history, tool output, screenshots, and thousands of response items — until it's too heavy to load, too risky to trust, and too big to read to figure out what's even in it.

Compaction trims what Codex keeps *in context*. It does nothing for the file sitting on disk, and it doesn't leave you anything durable to carry into a fresh task. So you're stuck choosing between grinding forward in a degraded session or starting over and losing everything you'd learned.

`codex-thread-tools` is the toolkit for that moment in between: spot the risk before it bites, pull out what's actually worth keeping, and get the rest out of your way — without ever treating raw transcripts as documentation.

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
npx codex-thread-tools health
```

Living with it day to day:

```bash
npm install -g codex-thread-tools
codex-thread-tools health
```

(The npm package wraps bundled Python tools — you'll need Node.js 18+ and Python 3 on `PATH`.)

Want Codex to prepare a handoff when you ask? Install the skill:

```bash
codex-thread-tools install-skill
```

Then just say `Use codex-thread-handoff` whenever a health report tells you it's time.

## How it works

1. **Inspect** — a health report selects one project session and scores independent risk domains, not just raw file size.
2. **Decide** — it tells you plainly: continue, monitor, or hand off, and shows the signals behind that call.
3. **Preserve** — handoff and archive tools keep the durable facts and visual evidence, and leave the bulky or sensitive payloads behind.
4. **Continue** — start clean with tight project context, while the old session stays around for recovery or verified archiving.

### Local health

```bash
codex-thread-tools health
codex-thread-tools health --mode standard
codex-thread-tools health --mode verbose --size-format both
codex-thread-tools health --json
```

The human-readable output is for your terminal. `--json` is the stable interface if you're scripting against it.
Health separates the latest turn from continuation risk. `WARN` means monitor the selected session; `DANGER` is what triggers handoff-now guidance. Successful compaction counts remain visible as scale information without requiring a handoff by themselves.
`--json` keeps existing machine-readable compatibility fields and adds state-first fields for compatible clients.

### Remote health

Install the same package on both ends, then:

```bash
codex-thread-tools health remote --host user@example-host \
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
- **Version:** `1.3.1`
- **Issues:** [Report a bug or request a feature](https://github.com/zenzig/codex-thread-tools/issues)
- **Security:** Read the [security policy](SECURITY.md) before reporting a vulnerability.
- **[Changelog](CHANGELOG.md):** Release history and notable changes.
- **Development:** See the [development guide](docs/development.md) for tests and package checks.
- **License:** [MIT](LICENSE)
