from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MEDIUM_ARTICLE_URL = (
    "https://medium.com/@atomicfalls/the-thread-that-ate-itself-what-happens-"
    "when-your-codex-session-gets-too-big-to-open-5ee559f263f3"
)


PUBLIC_DOCS = [
    "installation.md",
    "health.md",
    "handoff.md",
    "session-archive.md",
    "visual-archive.md",
    "recovery.md",
    "compaction.md",
    "publishing.md",
    "development.md",
]


def test_root_readme_is_concise_and_links_docs_index() -> None:
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    non_blank_lines = [line for line in text.splitlines() if line.strip()]

    assert len(non_blank_lines) <= 220
    assert "[Documentation](docs/README.md)" in text
    assert "## Documentation" in text
    assert "[Changelog](CHANGELOG.md)" in text


def test_health_docs_cover_remote_health_contract() -> None:
    text = (DOCS / "health.md").read_text(encoding="utf-8")

    assert "health remote --host" in text
    assert "--project /srv/project" in text
    assert "non-interactive SSH" in text
    assert "login shell" in text
    assert "NVM" in text
    assert "Raw session JSONL" in text
    assert "bounded remote stderr diagnostics" in text
    assert "subagent" in text.lower()
    assert "user-owned root" in text.lower()
    assert "remote token" in text.lower()
    assert "post-parse health-result codes" in text.lower()
    assert "fails closed" in text.lower()
    assert "node1.example.com" not in text
    assert "user@remote-host" not in text


def test_health_docs_capture_state_first_reporting_model() -> None:
    text = (DOCS / "health.md").read_text(encoding="utf-8")

    assert "Task state and continuation risk are separate" in text
    assert "active turn" in text
    assert "continuation risk" in text.lower()
    assert "codex-thread-tools health --mode standard" in text
    assert "codex-thread-tools health remote --host" in text
    assert "older remote host" in text.lower()
    assert "| Any | Any | `source-retired` |" in text
    assert "| `retired` | Any |" not in text
    assert "upgrade codex-thread-tools to version 1.3.0 or newer" in text
    assert "upgrade the remote host to protocol 1" not in text


def test_readme_is_a_concise_open_source_project_overview() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    headings = {
        line.removeprefix("## ").strip().lower()
        for line in text.splitlines()
        if line.startswith("## ")
    }

    for heading in (
        "the problem",
        "use it when you want to",
        "what's in the box",
        "quick start",
        "how it works",
        "documentation",
        "project",
    ):
        assert heading in headings
    for link in (
        "docs/README.md",
        "docs/installation.md",
        "docs/health.md",
        "docs/handoff.md",
        "SECURITY.md",
        "LICENSE",
        "https://github.com/zenzig/codex-thread-tools/issues",
    ):
        assert link in text
    assert "npm install -g codex-thread-tools" in text
    assert "codex-thread-tools health remote" in text
    assert "user@example-host" in text
    assert "/srv/project" in text
    assert "user@remote-host" not in text
    assert "/path/to/project" not in text
    assert "NVM" in text
    assert text.count(MEDIUM_ARTICLE_URL) == 1
    assert len(text.splitlines()) <= 170


def test_root_readme_lists_remote_health_command() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "health remote --host" in text


def test_public_docs_index_links_all_detail_pages() -> None:
    index = DOCS / "README.md"
    text = index.read_text(encoding="utf-8")

    for doc in PUBLIC_DOCS:
        assert f"]({doc})" in text
        assert (DOCS / doc).is_file()
    assert "[Changelog](../CHANGELOG.md)" in text


def test_public_docs_are_free_of_internal_placeholders() -> None:
    for path in [DOCS / "README.md", *(DOCS / doc for doc in PUBLIC_DOCS)]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b(TODO|TBD)\b", text)
        assert "documentation/agent-handoffs" not in text


def test_version_contract_is_exact() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert package["version"] == version
    assert f"**Version:** `{version}`" in readme


def test_handoff_redaction_documentation_is_explicit() -> None:
    text = (DOCS / "handoff.md").read_text(encoding="utf-8")

    assert "best-effort redaction" in text
    assert "review before sharing" in text


def test_recovery_documentation_leads_with_safe_diagnosis_and_bundle() -> None:
    text = (DOCS / "recovery.md").read_text(encoding="utf-8")

    assert "codex-thread-tools recover diagnose" in text
    assert "codex-thread-tools recover bundle" in text
    assert "does not modify the source session" in text.lower()
    assert "outside `~/.codex/sessions`" in text
    assert "legacy" in text.lower()
    assert "strip-compacted" in text
    assert "rebuild-window" in text


def test_health_json_and_archive_verification_contract_is_documented() -> None:
    development_text = (DOCS / "development.md").read_text(encoding="utf-8")
    archive_text = (DOCS / "session-archive.md").read_text(encoding="utf-8")

    assert "canonical diagnostics" in development_text
    assert "raw event" in development_text
    assert "manifest directory" in archive_text
    assert "reject" in archive_text.lower()


def test_release_compatibility_is_documented() -> None:
    text = (DOCS / "development.md").read_text(encoding="utf-8")
    normalized_text = " ".join(text.split())

    assert "protocol 1 accepts older remote reports that omit state fields" in normalized_text
    assert "additive fields" in normalized_text
    assert "runtime dependencies" in text
    assert normalized_text.count("protocol 1 accepts older remote reports that omit state fields") == 1
    assert "Version 1.2.0 adds `recover diagnose` and `recover bundle`" not in text


def test_archive_force_modes_document_staged_replacement_limits() -> None:
    session_text = (DOCS / "session-archive.md").read_text(encoding="utf-8")
    visual_text = (DOCS / "visual-archive.md").read_text(encoding="utf-8")

    assert "--force" in session_text
    assert "complete staged replacement" in session_text.lower()
    assert "transactional staged replacement" in session_text.lower()
    assert "not an in-place overlay" in session_text.lower()
    assert "--force" in visual_text
    assert "complete staged replacement" in visual_text.lower()
    assert "transactional staged replacement" in visual_text.lower()
    assert "not an in-place overlay" in visual_text.lower()


def test_archive_safety_behavior_is_documented() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    index_text = (DOCS / "README.md").read_text(encoding="utf-8")
    session_text = (DOCS / "session-archive.md").read_text(encoding="utf-8")
    visual_text = (DOCS / "visual-archive.md").read_text(encoding="utf-8")

    assert "staged, verified archives" in readme_text.lower()
    assert "recovery quarantine" in readme_text.lower()
    assert "staged, verified cold storage" in index_text.lower()
    assert "recovery_file" in session_text
    assert "fail closed" in session_text.lower()
    assert "advisory lock" in session_text.lower()
    assert "fail closed" in visual_text.lower()


def test_archive_documentation_calls_out_cleanup_and_crash_limitations() -> None:
    session_text = (DOCS / "session-archive.md").read_text(encoding="utf-8")
    visual_text = (DOCS / "visual-archive.md").read_text(encoding="utf-8")
    dev_text = (DOCS / "development.md").read_text(encoding="utf-8")

    assert "crash consistency is not guaranteed" in session_text.lower()
    assert "cleanup failures" in session_text.lower()
    assert "cleanup failures" in visual_text.lower()
    assert "not guaranteed to preserve" in dev_text.lower()


def test_repository_hygiene_ignores_archival_staging_artifacts() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    for pattern in (
        "**/codex-session-archives/",
        "**/.codex-thread-tools-staging-*",
        "**/.codex-thread-tools-backup-*",
        "**/.codex-thread-tools-reservation-*",
        "**/.codex-thread-tools-prune-*",
    ):
        assert pattern in ignore
