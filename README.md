<div align="center">

<img src="assets/agent-thread-tools-header.png" alt="Clockwork robots pull tangled threads from several coding-agent sessions into one braided cord that runs through a gauge, a filing cabinet, a bridge, and a crane onto a spool" width="100%">

# agent-thread-tools

**Keep one project going across many Claude Code and OpenAI Codex sessions, without replaying old transcripts.**

Health checks · Handoffs · Reference archive · Screenshot archive · Remote health · Recovery

<a href="#-quick-start-claude-code"><img src="https://img.shields.io/badge/Quick_start-3_commands-2F81F7?style=for-the-badge" alt="Quick start"></a>
<a href="#-why-not-just-let-claude-code-compact"><img src="https://img.shields.io/badge/Why-not_just_compact%3F-D97757?style=for-the-badge" alt="Why not just compact?"></a>
<a href="docs/README.md"><img src="https://img.shields.io/badge/Docs-project_guides-8250DF?style=for-the-badge" alt="Documentation"></a>

<img src="https://img.shields.io/badge/Claude_Code-first--class-D97757?style=flat-square&logo=claude&logoColor=white" alt="Claude Code: first-class">
<img src="https://img.shields.io/badge/OpenAI_Codex-supported-24292F?style=flat-square" alt="OpenAI Codex: supported">
<a href="https://www.npmjs.com/package/agent-thread-tools"><img src="https://img.shields.io/npm/v/agent-thread-tools.svg?style=flat-square&color=CB3837&logo=npm" alt="npm version"></a>
<a href="https://www.npmjs.com/package/agent-thread-tools"><img src="https://img.shields.io/npm/dm/agent-thread-tools.svg?style=flat-square" alt="npm downloads"></a>
<img src="https://img.shields.io/badge/node-%E2%89%A518-5FA04E?style=flat-square&logo=nodedotjs&logoColor=white" alt="Node 18 or newer">
<img src="https://img.shields.io/badge/python-3-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3">
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-yellow?style=flat-square" alt="License: MIT"></a>

</div>

> [!NOTE]
> **Formerly `codex-thread-tools`.** Version 2.0.0 added support for Claude Code and
> renamed the package. The old `codex-thread-tools` commands still work. To switch: `npm uninstall -g codex-thread-tools && npm install -g agent-thread-tools`.

agent-thread-tools checks how healthy your coding-agent sessions are and tells you when
a session should end. It then turns what the session learned into a short handoff file
that the next session loads automatically.

## 🧵 What's in the box

<table>
  <tr>
    <td align="center" width="33%">🩺<br><strong>Health checks</strong><br><sub>Scores every session's size, compactions, context use, and screenshots, then says continue, monitor, or hand off.</sub></td>
    <td align="center" width="33%">🌉<br><strong>Handoffs</strong><br><sub><code>/thread-handoff</code> writes a short, reviewed brief that the next session loads on its own.</sub></td>
    <td align="center" width="33%">🗂️<br><strong>Reference archive</strong><br><sub>Handoffs, specs, and screenshots live in <code>.reference/</code>, a local git repository that is never pushed.</sub></td>
  </tr>
  <tr>
    <td align="center" width="33%">🖼️<br><strong>Screenshot archive</strong><br><sub>Copies the screenshots that still matter out of a session and verifies the copies.</sub></td>
    <td align="center" width="33%">🛰️<br><strong>Remote health</strong><br><sub>Checks sessions on another machine over SSH. Only a privacy-filtered report comes back.</sub></td>
    <td align="center" width="33%">🛟<br><strong>Recovery</strong><br><sub>Diagnoses a damaged session, strips images Claude Code cannot process, and builds a redacted recovery bundle.</sub></td>
  </tr>
</table>

## 🤔 Why not just let Claude Code compact?

Compaction keeps a session running when its context fills up. It does not carry the
project forward.

| | 🗜️ Compaction alone | 🌉 With a handoff |
| --- | --- | --- |
| **When** | ⚠️ When the context window is nearly full, often mid-task | ✅ At a point you choose, after health flags the risk |
| **What is kept** | ⚠️ A summary the model writes for itself, usually unread | ✅ A handoff file you can read, edit, and correct |
| **After several rounds** | ⚠️ Summaries of summaries; early decisions blur | ✅ Each handoff is dated and committed, so earlier states stay readable |
| **Next session** | ⚠️ `/clear` or a new terminal starts with only `CLAUDE.md` and auto memory | ✅ Every new session also loads the latest handoff, through `CLAUDE.local.md` |
| **Screenshots** | ⚠️ Not carried into the summary | ✅ The ones that matter are copied to `.reference/` with a manifest |
| **Session file** | ⚠️ Keeps growing on disk | ✅ Health reports its size, compactions, and context use for every project |
| **Other agents** | ⚠️ The summary exists only inside that Claude session | ✅ The handoff is plain Markdown that Codex or any model can read |

> [!TIP]
> Use compaction to finish the task in front of you. Use a handoff when a piece of work
> ends, so the next session starts from a short, checked brief instead of a compressed
> transcript.

## 🚀 Quick start (Claude Code)

You need Node.js 18+ and Python 3 on your `PATH`.

```bash
npm install -g agent-thread-tools
agent-thread-tools install-skill --agent claude   # adds the /thread-handoff skill
agent-thread-tools health --agent claude          # checks every Claude Code project
```

Then, whenever health says `WARN` or `DANGER`, or a piece of work is done:

<table>
  <tr>
    <td align="center" width="25%">🩺<br><strong>1. Check</strong><br><sub><code>health --agent claude</code> shows which sessions are at risk.</sub></td>
    <td align="center" width="25%">🌉<br><strong>2. Hand off</strong><br><sub>Run <code>/thread-handoff</code> in that Claude Code session.</sub></td>
    <td align="center" width="25%">✍️<br><strong>3. Review</strong><br><sub>Read the handoff it wrote and correct anything wrong.</sub></td>
    <td align="center" width="25%">🧹<br><strong>4. Start fresh</strong><br><sub>Run <code>/clear</code>. The new session starts with the handoff loaded.</sub></td>
  </tr>
</table>

Pass `--agent claude` whenever `~/.codex/sessions` also exists on the machine; without
it, the tools read Codex sessions.

## 📦 What a handoff leaves behind

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

A handoff records the goal and next action, the current state, the decisions made and
why, the files involved, what was tested, and the open risks. `.reference/` and
`CLAUDE.local.md` are listed in the project's `.git/info/exclude`, so your project
repository ignores them and no tracked file changes.

## 🚦 Reading the health report

| Status | Action | What to do |
| :---: | --- | --- |
| ![OK](https://img.shields.io/badge/OK-2DA44E?style=flat-square) | **Continue** | Nothing. The session is healthy. |
| ![WARN](https://img.shields.io/badge/WARN-D4A72C?style=flat-square) | **Monitor** | Risk is rising, for example context use above 70%. Plan a handoff at the next break. |
| ![DANGER](https://img.shields.io/badge/DANGER-CF222E?style=flat-square) | **Handoff now** | Finish the current turn, then hand off. |

Health looks at session file size, item count, compactions, context use, and screenshots
that could break a reload. Exit codes are `0` (OK), `2` (WARN), and `3` (DANGER), so
scripts can act on them. Add `--json` for machine-readable output.

```bash
agent-thread-tools health --agent claude --mode standard
agent-thread-tools health check ~/.claude/projects/<project>/<session>.jsonl
```

## 🧰 Commands

| Command | What it does | Claude Code | Codex |
| --- | --- | :---: | :---: |
| 🩺 `health` | Reports session health for all projects or for one session file | ✅ | ✅ |
| 🧩 `install-skill` | Installs the handoff skill (`--agent claude` or `codex`) | ✅ | ✅ |
| 📝 `handoff-summary` | Drafts a redacted summary of a session to help write a handoff | ✅ | ✅ |
| 🗂️ `reference init` / `commit` | Creates and commits the local-only `.reference/` repository | ✅ | ✅ |
| 🖼️ `visual-archive` | Copies screenshots and videos out of a session and verifies the copies | ✅ | ✅ |
| 🔖 `handoff-marker` | Records which session a handoff came from | ✅ | ✅ |
| 🧊 `session-archive` | Moves old session files into staged, verified archives, with a recovery quarantine before pruning | ✅ | ✅ |
| 🛟 `recover` | Diagnoses a damaged session, repairs it, or builds a redacted recovery bundle | ✅ | ✅ |

> [!IMPORTANT]
> Health checks and summaries only read session files. Commands that copy or delete
> files run only when you name that subcommand, verify what they copied, and need an
> extra confirmation flag before deleting local session files.

## 🤖 Codex

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

📖 Background on why Codex sessions get too big to open: [The Thread That Ate Itself](https://medium.com/@atomicfalls/the-thread-that-ate-itself-what-happens-when-your-codex-session-gets-too-big-to-open-5ee559f263f3).

## 🛰️ Remote health

Check the sessions on another machine over SSH. Install the package on both machines,
then run:

```bash
agent-thread-tools health remote --host user@example-host --project /srv/project
```

The analysis runs on the remote host, and only a privacy-filtered report comes back: no
transcript text, tool output, or images cross SSH. If the command isn't found over a
non-interactive SSH session, it retries through your login shell, which covers NVM
installs. Add `--agent claude` or `--agent codex` to choose which sessions it reads.

## 📚 Documentation

Start at [Documentation](docs/README.md), or go straight to a guide:

| | Guide | Covers |
| :---: | --- | --- |
| 🟠 | [Claude Code](docs/claude-code.md) | Where sessions live, what health measures, the `/thread-handoff` skill |
| 📥 | [Installation](docs/installation.md) | `npx`, global npm, source checkout, and skill installation |
| 🩺 | [Thread health](docs/health.md) | Report modes, risk domains, remote reports, exit codes |
| 🌉 | [Handoff workflow](docs/handoff.md) | The Codex handoff skill, summaries, and markers |
| 🖼️ | [Visual archive](docs/visual-archive.md) | Keeping screenshots and videos outside session history |
| 🧊 | [Session archive](docs/session-archive.md) | Verified cold storage and pruning for old sessions |
| 🛟 | [Recovery](docs/recovery.md) | Diagnosis, repairs, and recovery bundles for damaged sessions |
| 🗜️ | [Compaction](docs/compaction.md) | How compaction differs from handoffs and archives |

## 📋 Project

<table>
  <tr><td>🏷️ <strong>Version</strong></td><td><code>2.0.0</code> · <a href="CHANGELOG.md">Changelog</a></td></tr>
  <tr><td>🐛 <strong>Issues</strong></td><td><a href="https://github.com/zenzig/agent-thread-tools/issues">Report a bug or request a feature</a></td></tr>
  <tr><td>🔒 <strong>Security</strong></td><td>Read the <a href="SECURITY.md">security policy</a> before reporting a vulnerability</td></tr>
  <tr><td>🛠️ <strong>Development</strong></td><td>See the <a href="docs/development.md">development guide</a> for tests and package checks</td></tr>
  <tr><td>⚖️ <strong>License</strong></td><td><a href="LICENSE">MIT</a></td></tr>
</table>
