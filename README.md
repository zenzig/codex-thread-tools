<div align="center">

# codex-thread-tools

**Small tools and a Codex skill for keeping long OpenAI Codex threads healthy.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.4.6-blue)](CHANGELOG.md)
[![Skills](https://img.shields.io/badge/skills-1-brightgreen)](#skill)
[![Tests](https://img.shields.io/badge/tests-pytest-brightgreen)](#testing)

<img src="assets/codex-thread-tools-header.png" alt="codex-thread-tools turns tangled Codex session threads into an organized spool" width="100%">

</div>

---

## What This Is

Current version: `0.4.6`

`codex-thread-tools` works with local session JSONL files under
`~/.codex/sessions/`.

Codex can now keep long conversations alive with several compaction systems.
That's good, but it doesn't mean a single thread should be treated as the
only place your project memory lives.

This repo gives you four practical things:

| Tool | What it does | Main command |
| --- | --- | --- |
| Health check | Reads Codex session files and tells you whether a thread looks ok, risky, or ready for handoff. | `codex-thread-tools health` |
| Visual archive | Copies screenshots and videos out of old threads into storage you choose, such as an external drive. | `codex-thread-tools visual-archive` |
| Handoff skill | Writes durable project context into your repository before starting a fresh Codex thread. | `codex-thread-tools install-skill` |
| Recovery starter | Helps inspect and back up damaged or oversized session files before any repair work. | `codex-thread-tools recover` |

You only need basic terminal knowledge, Node.js, and Python. You don't need to
understand the internal Codex session format to use the main commands.

> [!IMPORTANT]
> The npm package is a command wrapper around the bundled Python tools. `npx`
> and `npm install -g` make the commands easier to run, but Python 3 must still
> be available on your `PATH`.

---

## Quick Start

### Pick an install path

| Path | Best for | First command | Notes |
| --- | --- | --- | --- |
| `npx` | Trying the tools once without cloning the repo. | `npx codex-thread-tools health` | Downloads and runs the current npm package for that command. |
| Global npm install | Regular use from any terminal. | `npm install -g codex-thread-tools` | Gives you the persistent `codex-thread-tools` command. |
| Source checkout | Development, tests, fixtures, and local edits. | `git clone https://github.com/zenzig/codex-thread-tools.git` | Lets you run the Python scripts directly. |

### Run your first health check

Without installing:

```bash
npx codex-thread-tools health
```

After a global install:

```bash
npm install -g codex-thread-tools
codex-thread-tools health
```

From a source checkout:

```bash
git clone https://github.com/zenzig/codex-thread-tools.git
cd codex-thread-tools
python3 tools/codex-thread-health.py
```

That scans your Codex session folder, finds the most recent session for each
project, and prints a plain-English report.

If the report says `DANGER`, ask Codex to make a handoff:

```text
Use codex-thread-handoff to create a handoff before I start a new thread.
```

---

## Command Reference

Use the npm commands for normal use. Use the source commands when you're
developing this repository or working from a clone.

| Task | `npx` one-off | Global npm install | Source checkout |
| --- | --- | --- | --- |
| Project health report | `npx codex-thread-tools health` | `codex-thread-tools health` | `python3 tools/codex-thread-health.py` |
| One session health report | `npx codex-thread-tools health check <session.jsonl>` | `codex-thread-tools health check <session.jsonl>` | `python3 tools/codex-thread-health.py check <session.jsonl>` |
| Token usage report | `npx codex-thread-tools health tokens` | `codex-thread-tools health tokens` | `python3 tools/codex-thread-health.py tokens` |
| Record handoff marker | `npx codex-thread-tools handoff-marker record ...` | `codex-thread-tools handoff-marker record ...` | `python3 tools/codex-thread-handoff-marker.py record ...` |
| Scan visual references | `npx codex-thread-tools visual-archive scan <session.jsonl>` | `codex-thread-tools visual-archive scan <session.jsonl>` | `python3 tools/codex-visual-archive.py scan <session.jsonl>` |
| Archive visual references | `npx codex-thread-tools visual-archive archive <session.jsonl> ...` | `codex-thread-tools visual-archive archive <session.jsonl> ...` | `python3 tools/codex-visual-archive.py archive <session.jsonl> ...` |
| Inspect a damaged thread | `npx codex-thread-tools recover inspect <session.jsonl>` | `codex-thread-tools recover inspect <session.jsonl>` | `python3 tools/recover-codex-thread-starter.py inspect <session.jsonl>` |
| Install the handoff skill | `npx codex-thread-tools install-skill` | `codex-thread-tools install-skill` | copy or symlink `skills/codex-thread-handoff` |

### What npm and npx can do

| Works through npm or npx | Still requires a source checkout |
| --- | --- |
| Run health checks against your real `~/.codex/sessions` folder. | Running the test suite with `python3 -m pytest`. |
| Record local handoff sidecar markers. | Rebuilding synthetic fixture sessions. |
| Run visual archive scans, wizards, archive jobs, and verification. | Editing the Python tools or bundled skill. |
| Inspect and back up damaged session files. | Contributing patches back to this repo. |
| Install the bundled `codex-thread-handoff` skill into `~/.codex/skills/`. | Using source-only fixture paths like `tests/fixtures/sessions`. |

---

## Install The Skill

Codex creates `~/.codex/` when it runs. This repo assumes that directory already
exists on the machine where you use these tools.

Codex skills live in `~/.codex/skills/`. Only the `skills` subfolder may need to
be created. Install the bundled handoff skill with:

```bash
codex-thread-tools install-skill
```

Or run it once without a global install:

```bash
npx codex-thread-tools install-skill
```

<details>

<summary>Manual source checkout install</summary>

If you're working from a source checkout, you can copy the skill manually:

```bash
if ! test -d ~/.codex; then
  echo "Open Codex once so ~/.codex exists, then retry."
  exit 1
fi
test -d ~/.codex/skills || mkdir ~/.codex/skills
cp -R skills/codex-thread-handoff ~/.codex/skills/
```

</details>

<details>

<summary>Development symlink from this checkout</summary>

For local development, a symlink is easier because updates in this repo are used
immediately by Codex:

```bash
if ! test -d ~/.codex; then
  echo "Open Codex once so ~/.codex exists, then retry."
  exit 1
fi
test -d ~/.codex/skills || mkdir ~/.codex/skills
ln -s "$(pwd)/skills/codex-thread-handoff" ~/.codex/skills/codex-thread-handoff
```

</details>

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

```mermaid
flowchart LR
  A["Current Codex thread"] --> B{"Health check"}
  B -->|"OK"| C["Keep working"]
  B -->|"WARN"| D["Prepare a handoff"]
  B -->|"DANGER"| E["Create a handoff"]
  E --> F["Start a fresh thread"]
  D --> F
  F --> G["Continue from durable repo notes"]
```

---

## How Codex Compaction Works Now

Codex currently has richer compaction behavior than the old "summarize the
thread" mental model.

There are several paths:

| Path | What it means |
| --- | --- |
| Local compaction | Codex creates a smaller replacement history locally and persists it into the session JSONL. |
| Remote compaction | Codex asks the remote compaction system to produce a smaller context window. |
| Remote compaction v2 / standalone compaction | A newer flow carries forward state with an opaque compaction output item from `/responses/compact`. |
| Server-side compaction | The Responses API can compact during normal response generation when configured with `context_management` and `compact_threshold`. |

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

The important part is `payload.replacement_history`. That's the replacement
history Codex can use when rebuilding the live conversation. A `compacted`
record without a valid `replacement_history` is weaker and may be legacy or
malformed.

Remote compaction has a lifecycle:

1. A compaction request starts.
2. The request completes or fails.
3. The compacted result is installed as the live replacement history.

Step 2 by itself isn't enough. A request can complete without becoming the
actual live conversation state. The important boundary is when the replacement
history is installed.

Server-side and standalone compaction can emit opaque encrypted compaction
items. Those items carry prior state forward with fewer tokens, but they're
intentionally not human-readable. They help Codex, but they aren't durable
project notes for you.

---

## What Compaction Does Not Solve

Compaction reduces the context the model needs to see on later turns. It
doesn't solve every local thread failure mode.

A thread can still become unhealthy because:

- the session JSONL can keep growing on disk
- response and item counts can still approach API or app limits
- opaque compaction can preserve model-facing state without producing
  human-readable project notes
- failed compaction can leave a thread unable to continue cleanly
- legacy or malformed compacted records may not reconstruct well
- Codex may still struggle to load a very large session file

That's why this repo uses both health checks and handoffs.

---

## Thread Health Check

The main beginner command is:

```bash
codex-thread-tools health
```

You'll see one of four statuses:

| Status | Meaning | What to do |
| --- | --- | --- |
| `OK` | No major risk signals were found | Keep working |
| `WARN` | One risk area needs attention | Continue, but prepare a handoff if the task will keep growing |
| `DANGER` | The thread has strong risk signals | Make a handoff and start a fresh thread |
| `RETIRED` | The session was already handed off and is no longer the active thread | Use the replacement thread or the handoff file |

The health check is read-only. It doesn't edit, delete, trim, or repair any
Codex thread.

Reports separate active continuation health from handoff readiness. A thread can
be healthy enough to keep using while still needing visual archive notes before
it's retired.

Completed handoffs are tracked in a local sidecar marker file under
`~/.codex/thread-tools/`. Project health reports use those markers to retire old
source sessions and prioritize the new active replacement thread. Reports also
include the running total of completed handoffs per project.

If you check a retired source session directly, the top-level report is
`RETIRED` and exits successfully. The original health result is preserved as
underlying health for audit, but the pretty report doesn't present the retired
source as an active `WARN` or `DANGER` thread.

Large screenshot-heavy sessions can take a while to parse. In an interactive
terminal, the tool prints progress as it scans each session file. If your
terminal or editor hides stderr, force progress output with:

```bash
codex-thread-tools health --progress always
```

The default human report is table-first and uses raw byte counts so exact sizes
remain visible. Standard mode shows a project summary table plus readable action
summaries with full reasons for sessions that need attention. Use compact mode
when you want only the dashboard:

```bash
codex-thread-tools health --mode compact
```

Use verbose mode when you want the full diagnostic blocks, domain evidence, and
session file paths. Add human-readable sizes when byte counts are hard to scan:

```bash
codex-thread-tools health --mode verbose --size-format both
```

`--size-format` accepts `bytes`, `human`, or `both`. JSON output ignores the
pretty display mode and remains the stable scripting interface.

It looks at:

- session file size
- number of response items
- number of `compacted` checkpoints
- whether the latest compacted checkpoint has `replacement_history`
- compaction warning/error events
- unresolved aborted turns and error events
- active token usage, when Codex persisted it
- embedded screenshots, videos, and visual references
- whether compacted records dominate the file size

The report breaks those signals into five risk areas:

| Risk area | What it checks |
| --- | --- |
| `Load` | Disk size and unusually large JSONL records. |
| `Visuals` | Embedded screenshots/videos, missing visual files, and visuals inside compacted history. |
| `Compaction` | Failed, malformed, legacy, or repeatedly stressed compaction state. |
| `Limits` | Response item count and active context-window pressure. |
| `Continuity` | Missing session metadata, unresolved aborted turns, or error events. |

For visual payloads, the health check uses lightweight metrics. It estimates
embedded media size without hashing or copying the image/video bytes, so it can
still report on screenshot-heavy threads without turning the health check into
an archive operation.

Historical abort or error events are treated differently from unresolved ones.
If a later `turn_complete` or `task_complete` event is persisted, the health
check reports the historical abort/error as `WARN` instead of `DANGER`. If the
latest terminal event is still an abort or error, it remains `DANGER`.

A single successful compaction is normal. The health check looks for evidence
that compaction failed, a local compacted checkpoint lacks replacement history,
or compaction didn't let the thread continue cleanly. Opaque compaction items
alone aren't treated as a failure signal. It also
ignores normal user or assistant text that merely talks about compaction errors;
only persisted event records count as failure signals.

To record a completed handoff marker manually:

```bash
codex-thread-tools handoff-marker record \
  --source-session-file ~/.codex/sessions/YYYY/MM/DD/thread.jsonl \
  --replacement-session-file ~/.codex/sessions/YYYY/MM/DD/new-thread.jsonl \
  --handoff-file /path/to/documentation/agent-handoffs/YYYY-MM-DD-topic.md
```

The command appends one local sidecar event and prints a `Codex thread handoff
marker:` block to include in the new thread prompt. The marker file is local
state; don't commit it.

You can also run this command after an older handoff to backfill the local
sidecar marker. Backfilling records local state only; it doesn't modify the
Codex session JSONL. For older handoffs that didn't include the prompt marker
in the new thread, pass `--replacement-session-file` so health reports can show
which active session replaced the retired source.

For machine-readable output:

```bash
codex-thread-tools health --json
```

To check one specific session file:

```bash
codex-thread-tools health check ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

### Token usage report

To estimate Codex-persisted lifetime token usage by project:

```bash
codex-thread-tools health tokens
```

You can choose the same display modes for token reports:

```bash
codex-thread-tools health tokens --mode standard
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
Reported lifetime tokens: 6,444,312,107

Project Token Summary
Project             Lifetime       Sessions   Active    Context  Events
------------------  -------------  ---------  --------  -------  ------
/Users/you/project  2,836,762,422  123 (119)  122,268   47.32%   24,687
```

Use JSON when you want the per-session source records behind each project total:

```bash
codex-thread-tools health tokens --json
```

Treat this as a Codex session-scale report, not a billing ledger. Older sessions
may not contain `token_count` events, and missing token data is reported as
`not recorded` rather than guessed as zero.

For source-checkout tests and demos, use safe test mode. It refuses to read the
real live Codex session folder:

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
- sidecar and prompt markers that retire the old session and connect the new thread

Compaction helps Codex continue a conversation. A handoff helps a new thread
resume the project.

---

## Recovery Tool

If a Codex thread is already damaged or too large to load, start with:

```bash
codex-thread-tools recover inspect ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

Before any repair, make a backup:

```bash
codex-thread-tools recover backup ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
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

<details>

<summary>Show repository tree</summary>

```text
codex-thread-tools/
├── .github/
│   └── workflows/
│       └── publish-npm.yml
├── bin/
│   └── codex-thread-tools.js
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── package.json
├── SECURITY.md
├── VERSION
├── codex_thread_tools/
│   ├── display.py
│   ├── sessionlib.py
│   ├── sessionpaths.py
│   ├── handoff_markers.py
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
│   ├── test_display.py
│   ├── test_github_workflows.py
│   ├── test_npm_package.py
│   ├── test_thread_health.py
│   └── test_visual_artifacts.py
└── tools/
    ├── codex-thread-health.py
    ├── codex-thread-handoff-marker.py
    ├── codex-visual-archive.py
    └── recover-codex-thread-starter.py
```

</details>

---

## Testing

Run the tests:

```bash
python3 -m pytest
```

Check the npm package contents without publishing:

```bash
npm pack --dry-run
```

Rebuild the fixture session files:

```bash
python3 tests/fixtures/build_fixtures.py
```

The tests don't depend on your real `~/.codex/sessions` folder.

## Publishing

Publishing is handled through GitHub Actions so GitHub and npm releases stay in
sync. Add an npm automation token as the repository secret `NPM_TOKEN`, then
publish a GitHub release whose tag matches the package version, for example
`v0.4.6`. The `Publish npm package` workflow will:

- verify `VERSION` and `package.json` match
- verify the GitHub release tag matches the package version
- run `python3 -m pytest`
- check that the npm version has not already been published
- run `npm publish --dry-run`
- publish to npm with provenance

The workflow can also be run manually from the GitHub Actions tab. Ordinary
pushes to `main` do not publish npm.

---

## Public Repo Hygiene

This repository intentionally doesn't track local Codex usage artifacts. The
`.gitignore` excludes handoff files, local planning notes, generated visual
fixtures, archive output, and common tool caches.

> [!CAUTION]
> Do not commit real Codex session files, private-project handoffs,
> screenshots, screen recordings, or archive output.

If you need a fixture, generate a small synthetic one through
`tests/fixtures/build_fixtures.py`.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) before
opening issues or pull requests that involve session data.

---

## Visual Archive Tool

Screenshots and screen recordings can make a Codex thread grow quickly. They're
also important context. If a future thread needs to understand what a design
looked like, you shouldn't simply strip that data away and hope the next thread
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
codex-thread-tools visual-archive scan ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

If the scan reports local image paths as skipped, rerun it with the folder that
contains those files:

```bash
codex-thread-tools visual-archive scan ~/.codex/sessions/YYYY/MM/DD/thread.jsonl \
  --allow-local-root "/path/to/screenshots"
```

If the scan finds visuals you want to keep, use the interactive wizard:

```bash
codex-thread-tools visual-archive wizard ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
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
codex-thread-tools visual-archive archive ~/.codex/sessions/YYYY/MM/DD/thread.jsonl \
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
of a session file and copying files you didn't intend to archive.

Verify an archive later:

```bash
codex-thread-tools visual-archive verify /Volumes/CodexArchive/codex-visual-artifacts/my-project/navbar-design-screenshots/manifest.json
```

Verification checks that archived files still exist and that their byte size and
SHA-256 hash match the manifest.

The visual archive tool doesn't edit, delete, trim, or rewrite Codex session
files. It only scans a session and copies visual files into the archive location
you choose.

---

## License

MIT. See [LICENSE](LICENSE).
