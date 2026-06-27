# Visual Archive

Screenshots and screen recordings can make a Codex thread grow quickly. They
can also be important context. If a future thread needs to understand what a
design looked like, do not simply strip that data away and hope the next thread
remembers it.

Use the visual archive tool to copy visual references to storage you control.
That storage can be a USB drive, external drive, secondary internal drive, or a
synced folder.

## Workflow

The visual archive workflow has two phases:

1. `scan` reads the session and reports visual references.
2. `archive` or `wizard` copies visual files into your archive location and
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
- `handoff-snippet.md`: text to paste into a handoff `Assets / References` section
- `artifacts/`: copied image and video files, deduplicated by SHA-256

Local visual files are copied only when they resolve under an explicit
`--allow-local-root`. This prevents the tool from following arbitrary paths out
of a session file and copying files you did not intend to archive.

## Verify

Verify an archive later:

```bash
codex-thread-tools visual-archive verify /Volumes/CodexArchive/codex-visual-artifacts/my-project/navbar-design-screenshots/manifest.json
```

Verification checks that archived files still exist and that their byte size and
SHA-256 hash match the manifest.

The visual archive tool does not edit, delete, trim, or rewrite Codex session
files. It only scans a session and copies visual files into the archive location
you choose.
