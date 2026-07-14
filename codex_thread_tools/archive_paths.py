"""Path resolution helpers for archived file verification."""

from __future__ import annotations

from pathlib import Path


class ArchivePathError(ValueError):
    pass


def resolve_archive_member(archive_dir: Path, relative_path: str) -> Path:
    """Resolve one manifest member beneath archive_dir or raise ArchivePathError."""
    archive_root = archive_dir.expanduser().resolve()
    if not relative_path:
        raise ArchivePathError("archive path escapes manifest directory")
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ArchivePathError("archive path escapes manifest directory")

    resolved = (archive_root / candidate).resolve()
    try:
        resolved.relative_to(archive_root)
    except ValueError as exc:
        raise ArchivePathError("archive path escapes manifest directory") from exc
    return resolved
