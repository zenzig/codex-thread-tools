<div align="center">

# codex-thread-tools

**Small tools and a Codex skill for keeping long Codex threads healthy.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.4.0-blue)](CHANGELOG.md)
[![Skills](https://img.shields.io/badge/skills-1-brightgreen)](#skill)
[![Tests](https://img.shields.io/badge/tests-pytest-brightgreen)](#testing)

</div>

---

## What This Is

Current version: `0.4.0`

Codex can now keep long conversations alive with several compaction systems. That
is good, but it does not mean a single thread should be treated as the only
place your project memory lives.

This repo gives you four practical things:

- a **health check** script that reads Codex session files and tells you whether
  a thread looks ok, risky, or ready for handoff
- a **visual archive** script that copies screenshots and videos out of old
  threads into storage you choose, such as an external drive
- a **handoff skill** that writes durable project context into your repository
  before starting a fresh Codex thread
- a **recovery starter** for damaged or oversized session files

You only need basic terminal knowledge and Python. You do not need to understand
the internal Codex session format to use the main commands.

---

## Quick Start

Clone the repo:

```bash
git clone https://github.com/zenzig/codex-thread-tools.git
cd codex-thread-tools
```

Run the thread health check:

```bash
python3 tools/codex-thread-health.py
```

That scans your Codex session folder, finds the most recent session for each
project, and prints a plain-English report.

If the report says `DANGER`, ask Codex to make a handoff:

```text
Use codex-thread-handoff to create a handoff before I start a new thread.
```

---

## Install The Skill

Codex skills live in `~/.codex/skills/`. You can copy the bundled handoff skill there:

```bash
mkdir -p ~/.codex/skills
cp -R skills/codex-thread-handoff ~/.codex/skills/
```

For development, a symlink is easier because updates in this repo are used
immediately:

```bash
mkdir -p ~/.codex/skills
ln -s "$(pwd)/skills/codex-thread-handoff" ~/.codex/skills/codex-thread-handoff
```

Then, from any Codex thread, say:

```text
Use codex-thread-handoff.
```

---

## The Simple Rule

Use compaction to keep working inside the current thread.

Use a handoff when the thread is getting large, has compacted several times, or
contains important decisions that should survive outside the chat log.

Use repair tools only after a thread is already hard to load, has disappeared
from the sidebar, or has hit a compaction/context error.

---

## How Codex Compaction Works Now

Codex currently has richer compaction behavior than the old "summarize the
thread" mental model.

There are several paths:

- **Local compaction**: Codex creates a smaller replacement history locally and
  persists it into the session JSONL.
- **Remote compaction**: Codex asks the remote compaction system to produce a
  smaller context window.
- **Remote compaction v2 / standalone compaction**: a newer flow that carries
  forward state with an opaque compaction output item from `/responses/compact`.
- **Server-side compaction**: the Responses API can compact during normal
  response generation when configured with `context_management` and
  `compact_threshold`.

In a local Codex session file, the strongest sign that compaction succeeded is a
JSONL record like:

```json
{
  "type": "compacted",
  "payload": {
    "replacement_history": []
  }
}
```

The important part is `payload.replacement_history`. That is the replacement
history Codex can use when rebuilding the live conversation. A `compacted`
record without a valid `replacement_history` is weaker and may be legacy or
malformed.

Remote compaction has a lifecycle:

1. A compaction request starts.
2. The request completes or fails.
3. The compacted result is installed as the live replacement history.

Step 2 by itself is not enough. A request can complete without becoming the
actual live conversation state. The important boundary is when the replacement
history is installed.

Server-side and standalone compaction can emit opaque encrypted compaction
items. Those items carry prior state forward with fewer tokens, but they are
intentionally not human-readable. They are useful to Codex, not useful as
durable project notes for you.

---

## What Compaction Does Not Solve

Compaction reduces the context the model needs to see on later turns. It does
not solve every local thread failure mode.

A thread can still become unhealthy because:

- the session JSONL can keep growing on disk
- response and item counts can still approach API or app limits
- opaque compaction can preserve model-facing state without producing
  human-readable project notes
- failed compaction can leave a thread unable to continue cleanly
- legacy or malformed compacted records may not reconstruct well
- the desktop app may still struggle to load a very large session file

That is why this repo uses both health checks and handoffs.

---

## Thread Health Check

The main beginner command is:

```bash
python3 tools/codex-thread-health.py
```

You will see one of three statuses:

| Status | Meaning | What to do |
| --- | --- | --- |
| `OK` | No major risk signals were found | Keep working |
| `WARN` | One risk area needs attention | Continue, but prepare a handoff if the task will keep growing |
| `DANGER` | The thread has strong risk signals | Make a handoff and start a fresh thread |

The health check is read-only. It does not edit, delete, trim, or repair any
Codex thread.

Reports separate active continuation health from handoff readiness. A thread can
be healthy enough to keep using while still needing visual archive notes before
it is retired.

Large screenshot-heavy sessions can take a while to parse. In an interactive
terminal, the tool prints progress as it scans each session file. If your
terminal or editor hides stderr, force progress output with:

```bash
python3 tools/codex-thread-health.py --progress always
```

It looks at:

- session file size
- number of response items
- number of `compacted` checkpoints
- whether the latest compacted checkpoint has `replacement_history`
- compaction warning/error events
- aborted turns
- active token usage, when Codex persisted it
- embedded screenshots, videos, and visual references
- whether compacted records dominate the file size

The report breaks those signals into five risk areas:

- `Load`: disk size and unusually large JSONL records
- `Visuals`: embedded screenshots/videos, missing visual files, and visuals inside compacted history
- `Compaction`: failed, malformed, legacy, or repeatedly stressed compaction state
- `Limits`: response item count and active context-window pressure
- `Continuity`: missing session metadata, aborted turns, or error events

For visual payloads, the health check uses lightweight metrics. It estimates
embedded media size without hashing or copying the image/video bytes, so it can
still report on screenshot-heavy threads without turning the health check into
an archive operation.

A single successful compaction is normal. The health check looks for evidence
that compaction failed, a local compacted checkpoint lacks replacement history,
or compaction did not let the thread continue cleanly. Opaque compaction items
alone are not treated as a failure signal. It also
ignores normal user or assistant text that merely talks about compaction errors;
only persisted event records count as failure signals.

For machine-readable output:

```bash
python3 tools/codex-thread-health.py --json
```

To check one specific session file:

```bash
python3 tools/codex-thread-health.py check ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

### Token usage report

To estimate Codex-persisted lifetime token usage by project:

```bash
python3 tools/codex-thread-health.py tokens
```

The token report scans all session JSONL files under `~/.codex/sessions/`,
groups them by project, and sums the latest cumulative `token_count` total from
each token-bearing session. It also shows the latest active token estimate and
active context percentage for each project.

Example output:

```text
Codex Project Token Usage
Projects: 10 (10 with token usage)
Sessions: 278 (273 with token usage)
Reported lifetime tokens: 6444312107

/Users/you/project
  Lifetime tokens: 2836762422
  Sessions: 123 (119 with token usage)
  Latest active tokens: 122268
  Active context: 47.32%
  Token events: 24687
```

Use JSON when you want the per-session source records behind each project total:

```bash
python3 tools/codex-thread-health.py tokens --json
```

Treat this as a Codex session-scale report, not a billing ledger. Older sessions
may not contain `token_count` events, and missing token data is reported as
`not recorded` rather than guessed as zero.

For tests and demos, use safe test mode. It refuses to read the real live Codex
session folder:

```bash
python3 tools/codex-thread-health.py \
  --session-root tests/fixtures/sessions \
  --safe-test-mode
```

---

## Skill

The bundled skill is:

```text
codex-thread-handoff
```

Use `codex-thread-handoff` when:

- the health check says `WARN` or `DANGER`
- a major implementation slice is complete
- Codex reports a context-window or compaction error
- the model starts losing track of earlier decisions
- you want to start a new thread without losing project context

The skill writes a handoff file in the project repository. A good handoff keeps
the durable facts outside the chat:

- current task and next action
- branch and commit
- changed files
- decisions made
- commands/tests already run
- known risks and failures
- exact prompt to paste into a new Codex thread

Compaction helps Codex continue a conversation. A handoff helps a new thread
resume the project.

---

## Recovery Tool

If a Codex thread is already damaged or too large to load, start with:

```bash
python3 tools/recover-codex-thread-starter.py inspect ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

Before any repair, make a backup:

```bash
python3 tools/recover-codex-thread-starter.py backup ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

The recovery tool has safety guards:

- repair output cannot be written into `~/.codex/sessions/`
- live replacement requires `--replace-live`
- live replacement also requires `--confirm-replace-live` with the exact resolved
  path
- write operations refuse to run while Codex appears to be open

Treat repair commands as last-resort tools. Inspect first, back up before any
write, and prefer writing repaired output to a scratch path before replacing any
live session file.

---

## Repository Layout

```text
codex-thread-tools/
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── SECURITY.md
├── VERSION
├── codex_thread_tools/
│   ├── sessionlib.py
│   ├── sessionpaths.py
│   ├── thread_health.py
│   └── visual_artifacts.py
├── skills/
│   └── codex-thread-handoff/
│       ├── SKILL.md
│       ├── agents/openai.yaml
│       ├── references/handoff-workflow.md
│       └── references/handoff-template.md
├── tests/
│   ├── fixtures/
│   ├── test_thread_health.py
│   └── test_visual_artifacts.py
└── tools/
    ├── codex-thread-health.py
    ├── codex-visual-archive.py
    └── recover-codex-thread-starter.py
```

---

## Testing

Run the tests:

```bash
python3 -m pytest
```

Rebuild the fixture session files:

```bash
python3 tests/fixtures/build_fixtures.py
```

The tests do not depend on your real `~/.codex/sessions` folder.

---

## Public Repo Hygiene

This repository intentionally does not track local Codex usage artifacts. The
`.gitignore` excludes handoff files, local planning notes, generated visual
fixtures, archive output, and common tool caches.

Do not commit real Codex session files, private-project handoffs, screenshots,
screen recordings, or archive output. If you need a fixture, generate a small
synthetic one through `tests/fixtures/build_fixtures.py`.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) before
opening issues or pull requests that involve session data.

---

## Visual Archive Tool

Screenshots and screen recordings can make a Codex thread grow quickly. They are
also important context. If a future thread needs to understand what a design
looked like, you should not simply strip that data away and hope the next thread
remembers it.

Use the visual archive tool to copy visual references to storage you control.
That storage can be a USB drive, external drive, secondary internal drive, or a
synced folder. The tool treats it as a normal folder path.

The visual archive workflow has two phases:

1. `scan` reads the session and reports visual references.
2. `archive` or `wizard` copies the visual files into your archive location and
   writes handoff-ready manifests.

Start with a read-only scan:

```bash
python3 tools/codex-visual-archive.py scan ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

If the scan reports local image paths as skipped, rerun it with the folder that
contains those files:

```bash
python3 tools/codex-visual-archive.py scan ~/.codex/sessions/YYYY/MM/DD/thread.jsonl \
  --allow-local-root "/path/to/screenshots"
```

If the scan finds visuals you want to keep, use the interactive wizard:

```bash
python3 tools/codex-visual-archive.py wizard ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

The wizard asks for:

- archive location
- project name
- visual set name
- a short note explaining what the visuals preserve
- optional folder roots for local image files
- confirmation before copying anything

For advanced or repeatable use:

```bash
python3 tools/codex-visual-archive.py archive ~/.codex/sessions/YYYY/MM/DD/thread.jsonl \
  --archive-root "/Volumes/CodexArchive" \
  --project-name "My Project" \
  --artifact-set "navbar-design-screenshots" \
  --visual-context "Screenshots showing navbar color, spacing, and layout decisions."
```

The archive command writes:

- `manifest.json`: machine-readable inventory
- `manifest.md`: human-readable visual context
- `handoff-snippet.md`: text to paste into the handoff `Assets / References` section
- `artifacts/`: copied image and video files, deduplicated by SHA-256

Local visual files are copied only when they resolve under an explicit
`--allow-local-root`. This prevents the tool from following arbitrary paths out
of a session file and copying files you did not intend to archive.

Verify an archive later:

```bash
python3 tools/codex-visual-archive.py verify /Volumes/CodexArchive/codex-visual-artifacts/my-project/navbar-design-screenshots/manifest.json
```

Verification checks that archived files still exist and that their byte size and
SHA-256 hash match the manifest.

The visual archive tool does not edit, delete, trim, or rewrite Codex session
files. It only scans a session and copies visual files into the archive location
you choose.

---

## License

MIT. See [LICENSE](LICENSE).
