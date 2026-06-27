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
