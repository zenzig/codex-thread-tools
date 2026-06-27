# Installation

`codex-thread-tools` is for local OpenAI Codex session files under
`~/.codex/sessions/`.

The npm package is a command wrapper around bundled Python tools. `npx` and
`npm install -g` make the commands easier to run, but Python 3 must still be
available on your `PATH`.

## Choose An Install Path

| Path | Best for | Command |
| --- | --- | --- |
| `npx` | Trying the tools once without cloning the repo. | `npx codex-thread-tools health` |
| Global npm install | Regular use from any terminal. | `npm install -g codex-thread-tools` |
| Source checkout | Development, tests, fixtures, and local edits. | `git clone https://github.com/zenzig/codex-thread-tools.git` |

## Run A Health Check

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

## Install The Handoff Skill

Codex creates `~/.codex/` when it runs. This repo assumes that directory already
exists on the machine where you use these tools.

Codex skills live in `~/.codex/skills/`. Only the `skills` subfolder may need to
be created.

```bash
codex-thread-tools install-skill
```

Or run it once without a global install:

```bash
npx codex-thread-tools install-skill
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

Then, from any Codex thread, say:

```text
Use codex-thread-handoff.
```
