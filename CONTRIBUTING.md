# Contributing

Thanks for considering a contribution.

## Development

Run tests before opening a pull request:

```bash
python3 -m pytest
```

Rebuild generated fixtures when changing fixture builders:

```bash
python3 tests/fixtures/build_fixtures.py
```

## Privacy Rules

Do not commit real Codex session files, handoffs, screenshots, visual archives,
or machine-local planning notes. The repository intentionally ignores `docs/`,
handoff directories, generated visual fixtures, and archive output.

If a contribution needs an example session, add a small synthetic fixture through
`tests/fixtures/build_fixtures.py`.

## Pull Requests

Keep changes focused. Include:

- what changed
- why it changed
- how it was tested
- any safety or privacy implications
