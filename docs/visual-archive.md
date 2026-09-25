# Visual Archive

Screenshots and screen recordings make a session grow quickly. They can also be
important context. If a future session needs to understand what a design looked
like, do not simply strip that data away and hope the next session remembers it.

Use the visual archive tool to copy visual references to storage you control.
It reads Claude Code and Codex sessions; the format is detected from the file.
The archive location can be a project folder, a USB drive, an external drive, a
secondary internal drive, or a synced folder.

In Claude Code, `/thread-handoff` does this for you: it scans the session and
archives the screenshots that still matter into the project's `.reference/`
folder. See [Claude Code](claude-code.md).

## Workflow

The visual archive workflow has two phases:

1. `scan` reads the session and reports visual references.
2. `archive` or `wizard` copies visual files into your archive location and
   writes handoff-ready manifests.

Start with a read-only scan:

```bash
agent-thread-tools visual-archive scan ~/.claude/projects/<project>/<session>.jsonl
agent-thread-tools visual-archive scan ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
```

If the scan reports local image paths as skipped, rerun it with the folder that
contains those files:

```bash
agent-thread-tools visual-archive scan <session>.jsonl \
  --allow-local-root "/path/to/screenshots"
```

If the scan finds visuals you want to keep, use the interactive wizard:

```bash
agent-thread-tools visual-archive wizard <session>.jsonl
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
agent-thread-tools visual-archive archive <session>.jsonl \
  --archive-root "/Volumes/Archive" \
  --project-name "My Project" \
  --artifact-set "navbar-design-screenshots" \
  --visual-context "Screenshots showing navbar color, spacing, and layout decisions."
```

The archive root must already exist and must be outside `~/.claude/projects/` and
`~/.codex/sessions/`. The archive is written to
`visual-artifacts/<project>/<set>/` under it, and contains:

- `manifest.json`: machine-readable inventory
- `manifest.md`: human-readable visual context
- `handoff-snippet.md`: text to paste into a handoff `Assets / References` section
- `artifacts/`: copied image and video files, deduplicated by SHA-256

`--force` performs complete staged replacement, not an in-place overlay. This is
a transactional staged replacement: stale artifacts are removed only after the
full replacement is ready. Handled failures preserve or restore the prior archive
contents, but cleanup failures and process or OS crashes are not guaranteed to
preserve those contents.

Local visual files are copied only when they resolve under an explicit
`--allow-local-root`. This prevents the tool from following arbitrary paths out
of a session file and copying files you did not intend to archive.

## Verify

Verify an archive later:

```bash
agent-thread-tools visual-archive verify /Volumes/Archive/visual-artifacts/my-project/navbar-design-screenshots/manifest.json
```

Verification checks that archived files still exist and that their byte size and
SHA-256 hash match the manifest. Malformed manifests, unsupported schemas,
missing artifact metadata, and paths outside the archive fail closed.

The visual archive tool does not edit, delete, trim, or rewrite session files.
It only scans a session and copies visual files into the archive location you
choose.
