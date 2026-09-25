# Claude Code

`agent-thread-tools` reads Claude Code sessions as well as Codex sessions. Each
session file is checked on its own: Codex records carry a `payload`, and Claude
Code records are translated into the same shape before analysis.

## Where sessions live

Claude Code writes one JSONL file per session to
`~/.claude/projects/<project-dir>/<session-id>.jsonl`, where `<project-dir>` is the
project path with separators replaced by `-`. Subagent transcripts live under
`<session-id>/subagents/` and are skipped when a root is scanned.

## Health

```bash
agent-thread-tools health --agent claude
agent-thread-tools health check ~/.claude/projects/<project-dir>/<session-id>.jsonl
```

Without `--agent`, the tools use `~/.codex/sessions` when it exists and
`~/.claude/projects` otherwise.

What is measured for Claude Code:

| Metric | Source |
| --- | --- |
| Project and session | `cwd` and `sessionId` on each record |
| Turns | a user prompt opens a turn; `turn_duration` or an `end_turn` reply closes it; an interrupt aborts it; an API error message is an error |
| Compactions | `compact_boundary` records and the compact summary that follows |
| Context use | the latest reply's input, cache, and output tokens against the context window |
| Visuals | pasted and tool-result images, which Claude Code embeds as base64 |

The context window is 200,000 tokens unless a reply or compaction in the session
exceeds it, in which case 1,000,000 is assumed. Set `CLAUDE_CONTEXT_WINDOW` to fix it.

## Handoff skill

```bash
agent-thread-tools install-skill --agent claude
```

This installs `~/.claude/skills/thread-handoff`. Running `/thread-handoff` in a
session:

1. runs the health check and redacted summary on the current session;
2. archives screenshots that still matter and saves large reference text;
3. writes a dated handoff and puts stable facts into `CLAUDE.md`;
4. points `CLAUDE.local.md` at the latest handoff, so the next session loads it.

Handoffs, screenshots, and reference docs go in the project's `.reference/`
folder. The skill sets it up automatically: it is its own local git repository,
listed (with `CLAUDE.local.md`) in the project's `.git/info/exclude` so the project
repository ignores both without any tracked file changing, and each handoff is committed there. Nothing in
it is pushed. You can run the same steps yourself:

```bash
agent-thread-tools reference init                    # create .reference/ and hide it
agent-thread-tools reference commit -m "Add spec"    # commit everything in it
```

Then run `/clear` or start a new session: it starts from `CLAUDE.md`, the handoff,
and auto memory instead of the old transcript.

Health then links the two sessions. The session that was handed off shows as
retired, and a later session that loaded the handoff through `CLAUDE.local.md`
shows as its replacement ("Replacement active").

Handoff markers are kept in `~/.codex/thread-tools/handoff-markers.jsonl` when
Codex is installed, so one file covers both agents, and in
`~/.claude/thread-tools/handoff-markers.jsonl` otherwise. Set
`AGENT_THREAD_HANDOFF_MARKER_FILE` to use another file.

## Archive and recovery

Old sessions can move to external storage with `session-archive --agent claude`.
Each session's folder (subagents, tool results, workflows) travels with it, the
project's `memory/` folder is never touched, and sessions open in Claude Code are
skipped. See [Session archive](session-archive.md#claude-code).

`recover` reads Claude Code sessions too. `diagnose` also reports tool calls
without results and API errors about images, and `strip-images` removes images
that Claude Code cannot process. See [Recovery](recovery.md#claude-code).

Commands that write refuse to touch a session that is open in Claude Code. The
tool reads the open sessions from `~/.claude/sessions/`, where Claude Code
records each running session.
