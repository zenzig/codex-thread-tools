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
python3 tools/agent-thread-health.py
```

## Install The Handoff Skill

### Claude Code

In a terminal on the machine where Claude Code runs:

```bash
agent-thread-tools install-skill --agent claude
```

Or set it up from inside any Claude Code app, including the desktop app and the
mobile app through Remote Control. Send Claude this message; it runs the commands
on the machine where the session runs:

```text
Install agent-thread-tools with `npm install -g agent-thread-tools`, then run
`agent-thread-tools install-skill --agent claude`.
```

Claude may ask for permission before it runs them. The skill is installed to
`~/.claude/skills/thread-handoff`. If `/thread-handoff` is not in the slash-command
menu afterwards, start a new session.

### Codex

```bash
agent-thread-tools install-skill
```

The skill is installed to `~/.codex/skills/codex-thread-handoff`. Then, from any
Codex thread, say:

```text
Use the installed `codex-thread-handoff` skill to create a repository-backed
handoff for a new task. Do not use Codex's native Handoff or `handoff_thread`.
If the skill is unavailable, stop and report that it must be installed.
```

If Codex doesn't show the skill, reload Codex or start a new task.

Both installs need the agent to have run once on that machine, so that
`~/.claude/` or `~/.codex/` exists; the command says so if it doesn't. Run either
one without a global install by starting it with `npx`, for example
`npx agent-thread-tools install-skill --agent claude`.

### Keeping The Skill Current

The installed skill is a copy, so upgrading agent-thread-tools does not change
it. After each upgrade, run `install-skill` again (with `--agent claude` for
Claude Code), or ask Claude to run it for you.

### From A Source Checkout

For development, link the skill instead of copying it, so edits in the
repository take effect right away. In a terminal, from the root of the checkout:

```bash
# Claude Code
mkdir -p ~/.claude/skills
ln -s "$(pwd)/skills/thread-handoff" ~/.claude/skills/thread-handoff

# Codex
mkdir -p ~/.codex/skills
ln -s "$(pwd)/skills/codex-thread-handoff" ~/.codex/skills/codex-thread-handoff
```

Remove an installed copy first (`rm -r ~/.claude/skills/thread-handoff`) if one
exists, or the link is created inside it.
