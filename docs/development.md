# Development

Use a source checkout when you want to edit the tools, run tests, or contribute
patches.

```bash
git clone https://github.com/zenzig/agent-thread-tools.git
cd agent-thread-tools
```

## Repository Layout

```text
agent-thread-tools/
├── .github/workflows/publish-npm.yml
├── assets/                       README images
├── bin/agent-thread-tools.js     npm command wrapper
├── agent_thread_tools/           shared Python package
│   ├── claude_sessions.py        reads Claude Code records in the Codex record shape
│   ├── claude_recovery.py        Claude Code inspect, checks, and strip-images
│   ├── handoff_markers.py
│   ├── handoff_summary.py
│   ├── remote_health.py
│   ├── session_archive.py
│   ├── session_integrity.py
│   ├── sessionlib.py
│   ├── sessionpaths.py
│   ├── thread_health.py
│   ├── visual_artifacts.py
│   └── ...
├── docs/
├── skills/
│   ├── thread-handoff/           Claude Code skill (/thread-handoff)
│   └── codex-thread-handoff/     Codex skill
├── tests/
└── tools/                        one script per command, agent-thread-*.py
```

`bin/agent-thread-tools.js` maps each command to a script in `tools/`: for
example `agent-thread-tools health` runs `tools/agent-thread-health.py`. The
scripts share `agent_thread_tools/`.

## How Session Formats Are Read

The tools read Claude Code and Codex sessions with the same analyzers.
`sessionlib.iter_session_records` checks the format of each file: Codex records
pass through unchanged, and Claude Code records are translated by
`claude_sessions.py` into the Codex record shape (`session_meta`,
`response_item`, `event_msg`, `compacted`). Code that must see a format's own
records, such as the Claude Code checks in `claude_recovery.py`, reads the raw
lines instead.

## Testing

Run the tests:

```bash
python3 -m pytest
```

If npm tries to write to a root-owned cache in your environment, use a temporary
cache:

```bash
npm_config_cache=/private/tmp/agent-thread-tools-npm-cache python3 -m pytest
```

Check the npm package contents without publishing:

```bash
npm pack --dry-run --json
```

Rebuild the Codex fixture session files:

```bash
python3 tests/fixtures/build_fixtures.py
```

Claude Code test sessions are built inside the tests that use them, for example
`tests/test_claude_sessions.py` and `tests/test_claude_recovery.py`. The tests do
not depend on your real `~/.codex/sessions` or `~/.claude/projects` folders.

## 2.0.0 Compatibility

Version 2.0.0 renames the package from `codex-thread-tools` to
`agent-thread-tools` and keeps `codex-thread-tools` as a second command name.
Remote health still runs `codex-thread-tools` on the remote host, so it reaches
hosts running either package, and a 2.x client accepts 1.x remote hosts with a
version warning because the remote protocol is unchanged. `health remote` passes
`--agent` to the remote host only when you give it.

## 1.3.x Compatibility

Version 1.3.x keeps protocol compatibility with existing scripts while adding
state-first local and remote health results. The privacy-safe protocol 1 accepts
older remote reports that omit state fields and also accepts new reports with
validated additive fields. Version 1.3.1 normalizes warning-level remote
actions client-side so 1.3.0 remote reports remain compatible. Existing
runtime dependencies and CLI compatibility are unchanged.

Local health JSON uses canonical diagnostics rather than raw event snippets from
session records.

Recovery bundles are staged and transactional for handled failure paths. They
leave source sessions unchanged, but process or OS crashes are not guaranteed to preserve a partially written external destination. As with staged archive
replacement, handled cleanup failures and process or OS crashes are not
guaranteed to preserve prior external output.

## Public Repo Hygiene

This repository intentionally does not track local agent usage artifacts. The
`.gitignore` excludes private handoff files, local planning notes, generated
visual fixtures, archive output, and common tool caches.

Do not commit real Claude Code or Codex session files, private-project handoffs,
`.reference/` folders, screenshots, screen recordings, or archive output.

If you need a fixture, generate a small synthetic one: Codex fixtures through
`tests/fixtures/build_fixtures.py`, Claude Code sessions inside the test.

See [CONTRIBUTING.md](../CONTRIBUTING.md) and [SECURITY.md](../SECURITY.md)
before opening issues or pull requests that involve session data.
