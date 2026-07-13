from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


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


def test_health_docs_cover_remote_health_contract() -> None:
    text = (DOCS / "health.md").read_text(encoding="utf-8")

    assert "health remote --host" in text
    assert "--project /home/you/project" in text
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
    assert "NVM" in text
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


def test_public_docs_are_free_of_internal_placeholders() -> None:
    for path in [DOCS / "README.md", *(DOCS / doc for doc in PUBLIC_DOCS)]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b(TODO|TBD)\b", text)
        assert "documentation/agent-handoffs" not in text
