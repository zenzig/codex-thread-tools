# Security Policy

## Supported Versions

Only the latest release is supported.

Current version: `0.4.0`

## Reporting A Vulnerability

Please report security issues privately through GitHub security advisories when
available, or by contacting the repository owner directly.

Do not open a public issue containing sensitive Codex session data, private
project paths, screenshots, secrets, or handoff contents.

## Sensitive Data Guidance

This project works near local Codex session files. Treat those files as private
application state.

Do not commit:

- real `~/.codex/sessions` JSONL files
- generated handoff files from private projects
- screenshots or videos from private projects
- visual archive output
- local planning notes that mention private projects

If sensitive data is accidentally pushed, deleting it in a normal commit is not
enough. Rewrite history or recreate the repository, then rotate any exposed
secrets.
