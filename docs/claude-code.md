# Claude Code

`codex-thread-tools` reads Claude Code sessions as well as Codex sessions. Each
session file is checked on its own: Codex records carry a `payload`, and Claude
Code records are translated into the same shape before analysis.

## Where sessions live

Claude Code writes one JSONL file per session to
`~/.claude/projects/<project-dir>/<session-id>.jsonl`, where `<project-dir>` is the
project path with separators replaced by `-`. Subagent transcripts live under
`<session-id>/subagents/` and are skipped when a root is scanned.

## Health

```bash
codex-thread-tools health --agent claude
codex-thread-tools health check ~/.claude/projects/<project-dir>/<session-id>.jsonl
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
codex-thread-tools install-skill --agent claude
```

This installs `~/.claude/skills/thread-handoff`. Running `/thread-handoff` in a
session:

1. runs the health check and redacted summary on the current session;
2. archives screenshots that still matter and saves large reference text;
3. writes a dated handoff and puts stable facts into `CLAUDE.md`;
4. points `CLAUDE.local.md` at the latest handoff, so the next session loads it.

When the project has a `.reference/` directory, handoffs, screenshots, and
reference docs go there. Making `.reference/` its own local git repository
(ignored by the project repository) keeps that material versioned on the machine
without pushing it anywhere.

Then run `/clear` or start a new session: it starts from `CLAUDE.md`, the handoff,
and auto memory instead of the old transcript.

## Not yet supported

`session-archive` and `recover` still target Codex sessions only.
