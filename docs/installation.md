# Installation

`agent-thread-tools` is for local OpenAI Codex session files under
`~/.codex/sessions/` and Claude Code session files under `~/.claude/projects/`.

It was published as `codex-thread-tools` before 2.0.0. To switch, run
`npm uninstall -g codex-thread-tools && npm install -g agent-thread-tools`; the
`codex-thread-tools` command keeps working as an alias.

The npm package is a command wrapper around bundled Python tools. `npx` and
`npm install -g` make the commands easier to run, but Python 3 must still be
available on your `PATH`.

## Choose An Install Path

| Path | Best for | Command |
| --- | --- | --- |
| `npx` | Trying the tools once without cloning the repo. | `npx agent-thread-tools health` |
| Global npm install | Regular use from any terminal. | `npm install -g agent-thread-tools` |
| Source checkout | Development, tests, fixtures, and local edits. | `git clone https://github.com/zenzig/agent-thread-tools.git` |

## Run A Health Check

Without installing:

```bash
npx agent-thread-tools health
```

After a global install:

```bash
npm install -g agent-thread-tools
agent-thread-tools health
```

From a source checkout:

```bash
git clone https://github.com/zenzig/agent-thread-tools.git
cd agent-thread-tools
python3 tools/codex-thread-health.py
```

## Install The Handoff Skill

Codex creates `~/.codex/` when it runs. This repo assumes that directory already
exists on the machine where you use these tools.

Codex skills live in `~/.codex/skills/`. Only the `skills` subfolder may need to
be created.

```bash
agent-thread-tools install-skill
```

Or run it once without a global install:

```bash
npx agent-thread-tools install-skill
```

From a source checkout, you can copy the skill manually:

```bash
if ! test -d ~/.codex; then
  echo "Open Codex once so ~/.codex exists, then retry."
  exit 1
fi
test -d ~/.codex/skills || mkdir ~/.codex/skills
cp -R skills/codex-thread-handoff ~/.codex/skills/
```

A copied installation is a snapshot. If you copy it from this repository, npm
upgrades to `agent-thread-tools` do not refresh that copy, so run
`agent-thread-tools install-skill` after each upgrade to refresh the snapshot.

For local development, a symlink is better because updates in this repository are
used immediately by Codex:

```bash
if ! test -d ~/.codex; then
  echo "Open Codex once so ~/.codex exists, then retry."
  exit 1
fi
test -d ~/.codex/skills || mkdir ~/.codex/skills
ln -s "$(pwd)/skills/codex-thread-handoff" ~/.codex/skills/codex-thread-handoff
```

Then, from any Codex thread, say:

```text
Use the installed `codex-thread-handoff` skill to create a repository-backed
handoff for a new task. Do not use Codex's native Handoff or `handoff_thread`.
If the skill is unavailable, stop and report that it must be installed.
```

If you copied `codex-thread-handoff` rather than using the symlink method, that
snapshot can lag behind repo changes until you rerun `agent-thread-tools
install-skill`. If Codex still doesn't show the updated skill, reload Codex or
start a new task.
