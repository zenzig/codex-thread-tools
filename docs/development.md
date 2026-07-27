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
│   ├── session_integrity.py
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

## 1.3.0 Compatibility

Version 1.3.0 keeps protocol-compatibility with existing scripts while adding
state-first local and remote health results. Protocol 1 accepts older remote
reports that omit state fields and also accepts new reports with validated additive
fields (including compatibility metadata for clients). Existing runtime
dependencies and CLI compatibility are unchanged. Version 1.2.0 adds `recover diagnose` and `recover bundle` without adding runtime dependencies or changing existing CLI syntax.

Local health JSON uses canonical diagnostics rather than raw event snippets from
session records.

Recovery bundles are staged and transactional for handled failure paths. They
leave source sessions unchanged, but process or OS crashes are not guaranteed to preserve a partially written external destination. As with staged archive
replacement, handled cleanup failures and process or OS crashes are not
guaranteed to preserve prior external output.

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
