# Session Archive

Old threads can be useful as audit history, but Codex does not need old project
threads in `~/.codex/sessions/` to continue work in your current thread. If you
want cold storage without filling your local drive, use the session archive
tool.

The session archive workflow has four phases:

1. `plan` previews matching session files.
2. `archive` copies those files to external storage and writes a manifest.
3. `verify` checks archived file size and SHA-256 hashes against the manifest.
4. `prune-local` optionally deletes verified local JSONL files.

## Plan

Start with a read-only plan:

```bash
codex-thread-tools session-archive plan \
  --project "/Users/you/project" \
  --older-than 30d \
  --min-size 100MiB
```

## Archive

Archive matching sessions to a folder outside `~/.codex/sessions/`, such as an
external drive:

```bash
codex-thread-tools session-archive archive \
  --project "/Users/you/project" \
  --older-than 30d \
  --min-size 100MiB \
  --archive-root "/Volumes/CodexArchive" \
  --archive-name "project-old-threads"
```

The archive command writes:

- `manifest.json`: machine-readable inventory with source paths, archive paths,
  byte counts, timestamps, session IDs, and SHA-256 hashes
- `manifest.md`: human-readable archive summary
- `sessions/`: copied session JSONL files, preserving their relative session
  folder paths

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

## Verify

Verify the archive before deleting anything local:

```bash
codex-thread-tools session-archive verify \
  --manifest "/Volumes/CodexArchive/codex-session-archives/project-old-threads/manifest.json"
```

## Prune Local Copies

Only after verification passes, prune local copies:

```bash
codex-thread-tools session-archive prune-local \
  --manifest "/Volumes/CodexArchive/codex-session-archives/project-old-threads/manifest.json" \
  --confirm-prune-local
```

`prune-local` refuses to run while Codex appears to be open unless you pass
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

## Session Archive vs Visual Archive

Session archive keeps raw thread JSONL in cold storage. Visual archive extracts
screenshots and videos into handoff-ready manifests that a future fresh thread
can understand without loading the old conversation.
