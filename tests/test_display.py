from __future__ import annotations

from codex_thread_tools.display import (
    format_bytes,
    format_count,
    format_project,
    render_table,
    truncate_middle,
)


def test_format_bytes_defaults_to_comma_separated_bytes() -> None:
    assert format_bytes(354_094_244, "bytes") == "354,094,244 bytes"


def test_format_bytes_can_use_human_units() -> None:
    assert format_bytes(354_094_244, "human") == "337.7 MiB"


def test_format_bytes_can_show_human_and_raw_bytes() -> None:
    assert format_bytes(354_094_244, "both") == "337.7 MiB (354,094,244 bytes)"


def test_format_count_uses_grouping() -> None:
    assert format_count(2_353_000) == "2,353,000"
    assert format_count(None) == "not recorded"


def test_truncate_middle_preserves_start_and_end() -> None:
    value = "/Users/richolson/2026/codex-skills/tests/fixtures/sessions/healthy.jsonl"

    assert truncate_middle(value, 36) == "/Users/richol...ssions/healthy.jsonl"
    assert len(truncate_middle(value, 36)) == 36
    assert truncate_middle("short", 36) == "short"


def test_truncate_middle_honors_small_limits() -> None:
    assert truncate_middle("abcdefghij", 4) == "a..."
    assert truncate_middle("abcdefghij", 5) == "a...j"
    assert truncate_middle("abcdefghij", 6) == "ab...j"


def test_format_project_prioritizes_project_name() -> None:
    assert format_project("/Users/richolson/2026/codex-skills", 22) == ".../codex-skills"
    assert (
        format_project("/Users/richolson/Documents/Atomic Mail Server", 22)
        == ".../Atomic Mail Server"
    )
    assert (
        format_project("/Users/richolson/2026/capacitor-socket-io", 22)
        == "capacitor-socket-io"
    )
    assert format_project("/work/project-a", 22) == "/work/project-a"


def test_format_project_shortens_deep_absolute_paths_even_when_they_fit() -> None:
    assert format_project("/Users/richolson/2026/flasher", 32) == ".../flasher"
    assert format_project("/work/project-a", 32) == "/work/project-a"


def test_format_project_preserves_long_project_name_tail() -> None:
    formatted = format_project(
        "/Users/richolson/Projects/super-extremely-long-project-name",
        22,
    )

    assert len(formatted) <= 22
    assert formatted.startswith("super-ex")
    assert formatted.endswith("name")


def test_render_table_does_not_pad_final_column() -> None:
    lines = render_table(("Name", "Reason"), (("alpha", "short"),))

    assert lines[-1] == "alpha  short"
