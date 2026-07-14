# Development

Use a source checkout when you want to edit the tools, run tests, or contribute
patches.

```bash
git clone https://github.com/zenzig/codex-thread-tools.git
cd codex-thread-tools
```

## Repository Layout

```text
codex-thread-tools/
├── .github/workflows/publish-npm.yml
├── assets/codex-thread-tools-header.png
├── bin/codex-thread-tools.js
├── codex_thread_tools/
│   ├── display.py
│   ├── handoff_markers.py
│   ├── handoff_summary.py
│   ├── session_archive.py
│   ├── sessionlib.py
│   ├── sessionpaths.py
│   ├── thread_health.py
│   └── visual_artifacts.py
├── docs/
├── skills/codex-thread-handoff/
├── tests/
└── tools/
```

## Testing

Run the tests:

```bash
python3 -m pytest
```

If npm tries to write to a root-owned cache in your environment, use a temporary
cache:

```bash
npm_config_cache=/private/tmp/codex-thread-tools-npm-cache python3 -m pytest
```

Check the npm package contents without publishing:

```bash
npm pack --dry-run --json
```

Rebuild fixture session files:

```bash
python3 tests/fixtures/build_fixtures.py
```

The tests do not depend on your real `~/.codex/sessions` folder.

## 1.1.1 Compatibility

Version 1.1.1 doesn't change CLI syntax or add runtime dependencies. Local
health JSON now uses canonical diagnostics instead of preserving raw event
snippets from session records.

Session and visual archive replacements are now staged and transactional for
handled failure paths. Existing archives are preserved or restored when a
replacement step fails, but handled-cleanup failures and process/OS crashes are
not guaranteed to preserve the prior archive.

## Public Repo Hygiene

This repository intentionally does not track local Codex usage artifacts. The
`.gitignore` excludes private handoff files, local planning notes, generated
visual fixtures, archive output, and common tool caches.

Do not commit real Codex session files, private-project handoffs, screenshots,
screen recordings, or archive output.

If you need a fixture, generate a small synthetic one through
`tests/fixtures/build_fixtures.py`.

See [CONTRIBUTING.md](../CONTRIBUTING.md) and [SECURITY.md](../SECURITY.md)
before opening issues or pull requests that involve session data.
