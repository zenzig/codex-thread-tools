# Session Integrity And Recovery Bundle Design

## Purpose

Detect persisted Codex session records that are unsafe to replay, particularly
malformed model-visible image values, and produce a durable replacement-task
recovery bundle. The feature must preserve the original session file and must
not claim to repair Codex Desktop's stored thread.

This design addresses sessions such as a large, compacted rollout containing an
invalid `input[N].output[K].image_url`. Codex can reject the next request before
the task begins, leaving the last turn incomplete and the task unable to accept
new work.

## Research Alignment

The design was compared against OpenAI Codex main at commit
`643de86a190a38a5f4afa5e3a15edf48153f9c64` on 2026-07-18.

- App-server accepts inline image data URLs and rejects remote HTTP(S) image
  URLs, but it documents no endpoint for deleting or replacing one persisted
  history item. `thread/rollback` is deprecated and paginated threads do not
  support it.
- App-server can start a new thread, fork a thread, archive it, or delete it.
  Forking copies stored history, so it is not a recovery path when corruption is
  already within the retained history.
- Remote compaction V2 retains user, developer, and system messages. The
  retained-message text budget preserves `InputImage` items without charging
  their payload as text tokens, so repeated compaction can retain heavyweight or
  malformed image values.
- Codex stores persisted token and thread history differently for paginated
  threads. Their full items are read through paging APIs, not reconstructed as a
  monolithic history response.

The tool remains session-file based and portable. It does not depend on the
experimental app-server protocol or attempt to control Codex Desktop.

## Scope

Add two subcommands below the existing `recover` command:

```bash
codex-thread-tools recover diagnose SESSION.jsonl
codex-thread-tools recover bundle SESSION.jsonl --project-root PROJECT
```

`diagnose` is a read-only streaming inspection. `bundle` writes only new files
outside `~/.codex/sessions` and never changes the source session.

This release also adds additive, privacy-safe integrity counts to local health
reports. The existing health JSON fields remain unchanged.

Out of scope:

- Editing, truncating, replacing, or reopening an original session file.
- Calling private or experimental Codex Desktop APIs.
- Automatically archiving, deleting, or moving a task.
- Reconstructing model context from raw transcripts or tool outputs.
- Following a paginated thread's inherited `history_base` across other files.

## Detection Model

Create a pure `session_integrity` module that walks JSON values only in
canonical model-visible image fields:

- `image_url` in `input_image` / `InputImage` content.
- `imageUrl` in app-server `inputImage` content.
- The same input-image shapes in Codex `custom_tool_call_output` and
  `function_call_output` `output` lists, because they can become part of a
  later model replay.

It must not recursively inspect arbitrary tool payloads, schemas, or prose
that happens to contain an image-looking URL. Each finding carries only a
stable code, JSONL line number, input kind, and compacted-history context.
It never includes the image URL, image data, transcript text, or a payload
fingerprint.

Validation accepts a non-empty `data:image/<subtype>;base64,<payload>` URL only
when its Base64 syntax and padding are valid. HTTP(S), non-image media types,
empty payloads, invalid Base64, and malformed data URL structure are findings.
The validator performs bounded structural checks without retaining full image
payloads in reports.

The diagnosis also combines the image findings with pre-handoff safety signals,
including incomplete active turns and whether the source session declares
`history_base` metadata.

Any malformed model-visible image produces `DANGER`. An invalid image in a
compacted record explicitly says that the defect can still be replayed after
compaction.

## Commands And Output

### `recover diagnose`

The command prints an ASCII report by default and supports `--json`. It exits:

- `0` for no integrity finding.
- `2` for caution-only conditions, such as an incomplete turn without a
  malformed image.
- `3` for dangerous replay defects, including malformed model-visible image
  values.
- `1` for invalid CLI use, unreadable source, or malformed JSONL.

Default human output shows no more than 20 findings. `--json` includes every
finding necessary for a caller to create a bundle, with no image or transcript
content.

### `recover bundle`

The command first runs the same diagnostic pass and creates a unique directory
under `~/.codex/thread-tools/recovery-bundles/` by default. The output directory
can be overridden, but it is rejected when it is inside `~/.codex/sessions`.

The bundle contains:

- `integrity-report.json`: source identity, source SHA-256, and sanitized
  findings.
- `recovery.md`: explanation of why the task should be replaced and the
  evidence behind that decision.
- `handoff-template.md`: a checklist for Git status, diff, recent commits,
  project documentation, decisions, verification, and next action.
- `fresh-task-prompt.md`: a prompt for a new task that explicitly avoids
  resuming, forking, or trusting the broken transcript.
- `visual-decision.md`: a decision record that defaults to `Not archived` and
  links to `visual-archive scan` when project visuals may be required.
- `manifest.json`: bundle file hashes and source metadata.

Existing paths are never overwritten unless the caller supplies `--force`.
Bundle creation does not require Codex to be closed because it never modifies
the source. It records source size, mtime, and SHA-256 before and after reading;
if identity changed, it fails and retains no partial completed bundle.

## Health Integration

`thread_health` reuses the structural validator while it already streams each
session record. New additive metrics include:

- `invalid_image_urls`
- `invalid_image_urls_in_compacted_records`
- `remote_image_urls`
- `session_integrity_findings`
- `history_base_present`

The visuals risk domain is `DANGER` when invalid model-visible image values are
present. Its canonical reason distinguishes malformed live versus compacted
history. Remote health sends counts and canonical reasons only; it never sends
JSON pointers, file paths beyond existing project/file identity, payload sizes,
hashes, transcript values, or image data over SSH.

## Safety And Failure Handling

- Original session JSONL files are read-only for both commands.
- Reports and manifests never include transcript excerpts, raw tool payloads,
  image data, secrets, or full data URLs.
- A bundle cannot be written inside the live session tree.
- `--force` replaces only a prior bundle directory after staged output is fully
  validated; it never changes the source session.
- Source identity changes during read cause a failed result, not an ambiguous
  recovery artifact.
- JSONL parse failures report the line number and prevent bundle completion.
- Existing `recover strip-compacted` and `recover rebuild-window` remain clearly
  documented as advanced legacy recovery operations, not fixes for malformed
  persisted image data.

## Testing

Tests will be written before implementation and cover:

- Valid PNG/JPEG/WebP data URLs, invalid Base64, missing data URL structure,
  non-image types, empty payloads, and remote URLs.
- Canonical-field-only detection, ensuring prose and arbitrary tool text are
  not false positives.
- Compact-history classification, line numbers, pointer-only findings, and
  redaction of raw values.
- Health `DANGER` classification and stable additive JSON output.
- Recovery-bundle content, source identity verification, no-overwrite behavior,
  source-change failure, and live-session output rejection.
- CLI dispatch, exit codes, documentation links, npm package contents, and
  remote allowlisted-report behavior.

## Release

This is a new public diagnostic and recovery interface. Release it as `1.2.0`,
with synchronized `VERSION`, `package.json`, README, changelog, documentation,
and npm package tests.
