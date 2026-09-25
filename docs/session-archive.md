# Session Archive

Old sessions can be useful as audit history, but neither Claude Code nor Codex
needs them to continue work in a new session. Their files keep growing on disk. If
you want cold storage without filling your local drive, use the session archive
tool. It works with Claude Code sessions in `~/.claude/projects/` and Codex
sessions in `~/.codex/sessions/`.

The session archive workflow has four phases:

1. `plan` previews matching sessions.
2. `archive` copies those files to external storage and writes a manifest.
3. `verify` checks archived file size and SHA-256 hashes against the manifest.
4. `prune-local` optionally deletes the verified local copies.

## Choose The Agent

Pass `--agent claude` or `--agent codex` to `plan` and `archive`. Without it, the
tool reads Codex sessions when `~/.codex/sessions` exists and Claude Code sessions
otherwise. `--session-root` points it at another folder; without `--agent`, the
tool then tells the two layouts apart by their folders.

| | Claude Code | Codex |
| --- | --- | --- |
| Sessions read | `~/.claude/projects/<project>/<session-id>.jsonl`, plus the session's folder | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` |
| Archive folder | `claude-session-archives/` | `codex-session-archives/` |
| Open sessions | Skipped by `plan` and `archive`; `prune-local` refuses them | `prune-local` refuses while Codex appears to be open |

## Claude Code Sessions

Claude Code keeps each session as `<session-id>.jsonl` plus a folder of the same
name that holds subagent transcripts, tool results, and workflow files. The archive
treats them as one session: every file is copied, hashed in the manifest, verified,
and pruned together, and `prune-local` removes the emptied folder. In the manifest,
each folder file is its own entry with `companion_of` naming its session file.
`--min-size` counts the session file and its folder together. The project's
`memory/` folder is never touched.

The tool reads which sessions are open from `~/.claude/sessions/`, where Claude
Code records each running session. `plan` reports how many sessions it skipped
because they are open (`skipped_open` lists them in `--json` output). To include
one, exit that session (or run `/clear` in it) and rerun.

## Plan

Start with a read-only plan:

```bash
agent-thread-tools session-archive plan \
  --agent claude \
  --project "/Users/you/project" \
  --older-than 30d \
  --min-size 100MiB
```

`--project` matches the project path recorded in the session. Use `--agent codex`
for Codex sessions.

## Archive

Archive matching sessions to a folder outside the session root, such as an
external drive:

```bash
agent-thread-tools session-archive archive \
  --agent claude \
  --project "/Users/you/project" \
  --older-than 30d \
  --min-size 100MiB \
  --archive-root "/Volumes/Archive" \
  --archive-name "project-old-sessions"
```

This writes to `/Volumes/Archive/claude-session-archives/project-old-sessions/`
(`codex-session-archives/` for Codex). The archive command writes:

- `manifest.json`: machine-readable inventory with the agent, source paths,
  archive paths, byte counts, timestamps, session IDs, and SHA-256 hashes
- `manifest.md`: human-readable archive summary
- `sessions/`: copied session files, preserving their relative paths under the
  session root

Verification resolves archived session paths from the manifest directory. It
rejects paths outside that directory, including traversal and symlink escapes.
Malformed manifests, unsupported schemas, missing metadata, and invalid paths
fail closed instead of being treated as verified archives.

Cleanup of local session files uses a staged quarantine first, then verifies
captured metadata before deleting originals. If a source changes between
preflight and delete, the tool rolls files back to their original paths and
preserves the local session tree. If another file appears at an original path
before rollback, the new file remains untouched and the captured session stays
in quarantine; the command reports its location as `recovery_file`.
If deletion of a quarantined session fails, the tool uses the same rule: it
restores the session to its original path when that path is still free, and
otherwise preserves the quarantined copy as `recovery_file`.
When rollback succeeds after a validation failure, the affected session is
reported as `restored` with the validation diagnostic, rather than as stranded
in recovery storage.

## Verify

Verify the archive before deleting anything local:

```bash
agent-thread-tools session-archive verify \
  --manifest "/Volumes/Archive/claude-session-archives/project-old-sessions/manifest.json"
```

## Prune Local Copies

Only after verification passes, prune local copies:

```bash
agent-thread-tools session-archive prune-local \
  --manifest "/Volumes/Archive/claude-session-archives/project-old-sessions/manifest.json" \
  --confirm-prune-local
```

`prune-local` reads the agent from the manifest:

- Claude Code: it refuses sessions that are open in Claude Code. If any session in
  the manifest is open, nothing is deleted.
- Codex: it refuses to run while Codex appears to be open unless you pass
  `--allow-codex-running`. Closing Codex first is safer because the app may be
  reading or writing session files.

Use `--json` on any phase when you want machine-readable output.

Operations for the same archive target are serialized with a hidden, persistent
advisory lock file in the archive's parent directory. The file is intentionally
reused between runs; the operating system lock, not its stored PID metadata,
determines whether another process owns the target.

Use `--force` for complete staged replacement of an existing archive. This is a
transactional staged replacement, not an in-place overlay: the old archive
remains in place until the full replacement is ready. Handled failures preserve
or restore the prior archive contents before rethrowing, but cleanup failures and
process or OS crashes are not guaranteed to preserve the previous archive.
Crash consistency is not guaranteed.

If cleanup of the prior archive fails after the replacement is already live, the
command succeeds and retains the hidden backup directory for recovery or manual
removal.

## Session Archive vs Visual Archive

Session archive keeps raw session files in cold storage. Visual archive extracts
screenshots and videos into handoff-ready manifests that a future fresh session
can understand without loading the old conversation.
