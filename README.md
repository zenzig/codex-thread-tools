<div align="center">

# agent-thread-tools

**Keep one project going across many Claude Code sessions, without replaying old transcripts.**

[![npm version](https://img.shields.io/npm/v/agent-thread-tools.svg)](https://www.npmjs.com/package/agent-thread-tools)
[![npm downloads](https://img.shields.io/npm/dm/agent-thread-tools.svg)](https://www.npmjs.com/package/agent-thread-tools)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Documentation](https://img.shields.io/badge/docs-project_guides-brightgreen.svg)](docs/README.md)

<img src="assets/agent-thread-tools-header.png" alt="Clockwork robots pull tangled threads from several coding-agent sessions into one braided cord that runs through a gauge, a filing cabinet, a bridge, and a crane onto a spool" width="100%">

</div>

agent-thread-tools checks how healthy your coding-agent sessions are and tells you
when a session should end. It then turns what the session learned into a short
handoff file that the next session loads automatically. It works with
**Claude Code** and **OpenAI Codex**. It was called `codex-thread-tools` before
version 2.0.0, and that command still works.

## Why not just let Claude Code compact?

Compaction keeps a session running when its context fills up. It does not carry
the project forward:

| | Compaction alone | With agent-thread-tools |
| --- | --- | --- |
| When it happens | When the context window is nearly full, often mid-task | At a point you choose, after health says the session is at risk |
| What is kept | A summary the model writes for itself, usually unread | A handoff file you can read, edit, and correct |
| After several rounds | Summaries of summaries; early decisions blur | Each handoff is dated and committed, so earlier states stay readable |
| Next session | `/clear` or a new terminal starts with only `CLAUDE.md` and auto memory | Every new session also loads the latest handoff, through `CLAUDE.local.md` |
| Screenshots | Not carried into the summary | The ones that matter are copied to `.reference/` with a manifest |
| The session file | Keeps growing on disk | Health reports its size, compactions, and context use for every project |
| Other agents | The summary exists only inside that Claude session | The handoff is plain Markdown that Codex or any model can read |

Use compaction to finish the task in front of you. Use a handoff when a piece of
work ends, so the next session starts from a short, checked brief instead of a
compressed transcript.

## Quick start (Claude Code)

You need Node.js 18+ and Python 3 on your `PATH`.

```bash
npm install -g agent-thread-tools
agent-thread-tools install-skill --agent claude   # adds the /thread-handoff skill
agent-thread-tools health --agent claude          # checks every Claude Code project
```

Pass `--agent claude` whenever `~/.codex/sessions` also exists on the machine;
without it, the tools read Codex sessions.

When health says `WARN` or `DANGER`, or when you finish a piece of work:

1. In Claude Code, run `/thread-handoff`.
2. Read the handoff it writes and correct anything wrong.
3. Run `/clear`, or open a new session. It starts with the handoff already loaded.

## What a handoff leaves behind

```text
your-project/
├── CLAUDE.md                 stable facts: architecture, conventions, commands
├── CLAUDE.local.md           points to the latest handoff; loaded every session
└── .reference/               local git repository, never pushed
    ├── INDEX.md              one line per saved document or screenshot set
    ├── handoffs/             one dated handoff per session, e.g. 2026-09-24-login-flow.md
    ├── docs/                 long pasted specs worth keeping
    └── codex-visual-artifacts/<project>/<set>/   archived screenshots and their manifest
```

A handoff records the goal and next action, the current state, the decisions made
and why, the files involved, what was tested, and the open risks. `.reference/` and
`CLAUDE.local.md` are listed in the project's `.git/info/exclude`, so your project
repository ignores them and no tracked file changes.

## Reading the health report

Each project gets a status and a recommended action:

| Status | Action | Meaning |
| --- | --- | --- |
| `OK` | Continue | The session is healthy. |
| `WARN` | Monitor | Risk is rising, for example context use above 70%. Plan a handoff at the next break. |
| `DANGER` | Handoff now | Finish the current turn, then hand off. |

Health looks at session file size, item count, compactions, context use, and
screenshots that could break a reload. Exit codes are `0` (OK), `2` (WARN), and
`3` (DANGER), so scripts can act on them. Add `--json` for machine-readable output.

```bash
agent-thread-tools health --agent claude --mode standard
agent-thread-tools health check ~/.claude/projects/<project>/<session>.jsonl
```

## Commands

| Command | What it does | Claude Code | Codex |
| --- | --- | :---: | :---: |
| `health` | Reports session health for all projects or for one session file | ✓ | ✓ |
| `install-skill` | Installs the handoff skill (`--agent claude` or `codex`) | ✓ | ✓ |
| `handoff-summary` | Drafts a redacted summary of a session to help write a handoff | ✓ | ✓ |
| `reference init` / `commit` | Creates and commits the local-only `.reference/` repository | ✓ | ✓ |
| `visual-archive` | Copies screenshots and videos out of a session and verifies the copies | ✓ | ✓ |
| `handoff-marker` | Records which session a handoff came from | ✓ | ✓ |
| `session-archive` | Moves old session files into staged, verified archives, with a recovery quarantine before pruning | | ✓ |
| `recover` | Diagnoses a damaged session and builds a redacted recovery bundle | | ✓ |

Health checks and summaries only read session files. Commands that copy or delete
files run only when you name that subcommand, verify what they copied, and need an
extra confirmation flag before deleting local session files.

## Codex

Install the Codex skill and check Codex sessions (`~/.codex/sessions`):

```bash
agent-thread-tools install-skill
agent-thread-tools health
```

To hand off, ask Codex in the thread:

```text
Use the installed `codex-thread-handoff` skill to create a repository-backed
handoff for a new task. Do not use Codex's native Handoff or `handoff_thread`.
If the skill is unavailable, stop and report that it must be installed.
```

Background on why Codex sessions get too big to open: [The Thread That Ate Itself](https://medium.com/@atomicfalls/the-thread-that-ate-itself-what-happens-when-your-codex-session-gets-too-big-to-open-5ee559f263f3).

## Remote health

Check the sessions on another machine over SSH. Install the package on both
machines, then run:

```bash
agent-thread-tools health remote --host user@example-host --project /srv/project
```

The analysis runs on the remote host, and only a privacy-filtered report comes
back: no transcript text, tool output, or images cross SSH. If the command isn't
found over a non-interactive SSH session, it retries through your login shell,
which covers NVM installs.

## Documentation

Start at [Documentation](docs/README.md), or go straight to:

| Guide | Topic |
| --- | --- |
| [Claude Code](docs/claude-code.md) | Where sessions live, what health measures, the `/thread-handoff` skill. |
| [Installation](docs/installation.md) | `npx`, global npm, source checkout, and skill installation. |
| [Thread health](docs/health.md) | Report modes, risk domains, remote reports, exit codes. |
| [Handoff workflow](docs/handoff.md) | The Codex handoff skill, summaries, and markers. |
| [Visual archive](docs/visual-archive.md) | Keeping screenshots and videos outside session history. |
| [Session archive](docs/session-archive.md) | Verified cold storage and pruning for Codex sessions. |
| [Recovery](docs/recovery.md) | Diagnosis and recovery bundles for damaged Codex sessions. |
| [Compaction](docs/compaction.md) | How compaction differs from handoffs and archives. |

## Project

- **Version:** `2.0.0` ([Changelog](CHANGELOG.md))
- **Issues:** [Report a bug or request a feature](https://github.com/zenzig/agent-thread-tools/issues)
- **Security:** Read the [security policy](SECURITY.md) before reporting a vulnerability.
- **Development:** See the [development guide](docs/development.md) for tests and package checks.
- **License:** [MIT](LICENSE)
