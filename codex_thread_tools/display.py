"""Text formatting helpers for codex-thread-tools CLI output."""

from __future__ import annotations

from typing import Any, Iterable, Sequence


def format_count(value: Any) -> str:
    if value is None:
        return "not recorded"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def format_bytes(value: int, size_format: str = "bytes") -> str:
    raw = f"{value:,} bytes"
    if size_format == "bytes":
        return raw

    human = _format_binary_bytes(value)
    if size_format == "human":
        return human
    if size_format == "both":
        return f"{human} ({raw})"
    raise ValueError(f"unknown size format: {size_format}")


def truncate_middle(value: str, max_length: int) -> str:
    if max_length <= 0:
        return ""
    if len(value) <= max_length:
        return value
    if max_length <= 3:
        return "." * max_length

    marker = "..."
    remaining = max_length - len(marker)
    start = min(max(1, remaining // 3 + 2), remaining)
    if remaining > 1:
        start = min(start, remaining - 1)
    end = remaining - start
    suffix = value[-end:] if end else ""
    return f"{value[:start]}{marker}{suffix}"


def format_project(value: str, max_length: int) -> str:
    if max_length <= 0:
        return ""
    if len(value) <= max_length and not _should_shorten_project_path(value):
        return value

    project_name = _path_name(value)
    if not project_name:
        return truncate_middle(value, max_length)

    prefix = ".../"
    if len(prefix) >= max_length:
        return truncate_middle(project_name, max_length)

    full_project_name = f"{prefix}{project_name}"
    if len(full_project_name) <= max_length:
        return full_project_name
    if len(project_name) <= max_length:
        return project_name

    return truncate_middle(project_name, max_length)


def render_table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    materialized = [list(row) for row in rows]
    widths = [len(header) for header in headers]
    for row in materialized:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    lines = [_join_table_row(headers, widths), _join_table_row(["-" * width for width in widths], widths)]
    for row in materialized:
        lines.append(_join_table_row(row, widths))
    return lines


def _join_table_row(row: Sequence[str], widths: Sequence[int]) -> str:
    cells: list[str] = []
    last_index = len(row) - 1
    for index, cell in enumerate(row):
        cells.append(cell if index == last_index else cell.ljust(widths[index]))
    return "  ".join(cells).rstrip()


def _format_binary_bytes(value: int) -> str:
    units = ("bytes", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    unit = units[0]
    for candidate in units[1:]:
        if amount < 1024:
            break
        amount /= 1024
        unit = candidate
    if unit == "bytes":
        return f"{value:,} bytes"
    return f"{amount:.1f} {unit}"


def _path_name(value: str) -> str:
    normalized = value.rstrip("/\\").replace("\\", "/")
    return normalized.rsplit("/", 1)[-1]


def _should_shorten_project_path(value: str) -> bool:
    normalized = value.rstrip("/\\").replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if len(parts) < 4:
        return False
    return normalized.startswith("/") or _has_windows_drive(parts[0])


def _has_windows_drive(part: str) -> bool:
    return len(part) == 2 and part[1] == ":"
