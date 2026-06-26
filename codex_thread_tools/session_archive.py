"""Archive Codex session JSONL files to external storage with manifests."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from codex_thread_tools.display import format_bytes, format_count
from codex_thread_tools.sessionlib import iter_jsonl, now_iso, now_stamp, record_timestamp
from codex_thread_tools.thread_health import extract_project, extract_session_id


MANIFEST_TYPE = "codex_session_archive_manifest"
MANIFEST_VERSION = 1


def build_archive_plan(
    *,
    session_root: Path,
    project: str | None,
    older_than: str | None,
    min_size: str | None,
    now: str | None = None,
) -> dict[str, Any]:
    resolved_root = session_root.expanduser().resolve()
    require_session_root(resolved_root)
    now_dt = parse_now(now)
    min_size_bytes = parse_size(min_size or "0")
    cutoff = (
        now_dt - parse_duration(older_than)
        if older_than
        else None
    )
    candidates = [
        session_record(path, resolved_root)
        for path in sorted(resolved_root.rglob("*.jsonl"))
        if path.is_file()
    ]
    candidates = [
        candidate
        for candidate in candidates
        if matches_project(candidate, project)
        and candidate["size_bytes"] >= min_size_bytes
        and (cutoff is None or parse_timestamp(candidate["activity_at"]) < cutoff)
    ]
    return {
        "report_type": "session_archive_plan",
        "session_root": str(resolved_root),
        "project": project or "",
        "selection": {
            "older_than": older_than or "",
            "min_size": min_size or "0",
            "min_size_bytes": min_size_bytes,
            "now": now_dt.isoformat().replace("+00:00", "Z"),
        },
        "summary": {
            "candidate_count": len(candidates),
            "total_bytes": sum(candidate["size_bytes"] for candidate in candidates),
        },
        "candidates": candidates,
    }


def archive_sessions(
    *,
    session_root: Path,
    archive_root: Path,
    project: str | None,
    older_than: str | None,
    min_size: str | None,
    archive_name: str | None,
    now: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    resolved_session_root = session_root.expanduser().resolve()
    resolved_archive_root = archive_root.expanduser().resolve()
    require_archive_root_outside_session_root(resolved_archive_root, resolved_session_root)
    plan = build_archive_plan(
        session_root=resolved_session_root,
        project=project,
        older_than=older_than,
        min_size=min_size,
        now=now,
    )
    archive_dir = resolved_archive_root / "codex-session-archives" / (
        archive_name or default_archive_name(project)
    )
    if archive_dir.exists() and not force:
        raise ValueError(f"archive already exists: {archive_dir} (use --force to overwrite)")
    archive_dir.mkdir(parents=True, exist_ok=True)
    session_dir = archive_dir / "sessions"
    archived: list[dict[str, Any]] = []
    for candidate in plan["candidates"]:
        source = Path(candidate["source_file"])
        destination = session_dir / candidate["source_relative_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        sha256 = sha256_file(destination)
        archived.append(
            {
                **candidate,
                "archive_file": str(destination),
                "archive_relative_path": str(destination.relative_to(archive_dir)),
                "sha256": sha256,
            }
        )
    manifest = {
        "type": MANIFEST_TYPE,
        "version": MANIFEST_VERSION,
        "created_at": now_iso(),
        "session_root": str(resolved_session_root),
        "archive_root": str(resolved_archive_root),
        "archive_dir": str(archive_dir),
        "manifest_file": str(archive_dir / "manifest.json"),
        "project": project or "",
        "selection": plan["selection"],
        "summary": {
            "archived_count": len(archived),
            "total_bytes": sum(item["size_bytes"] for item in archived),
        },
        "sessions": archived,
    }
    write_manifest(manifest)
    write_markdown_manifest(manifest)
    return manifest


def verify_archive(manifest_file: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_file)
    results: list[dict[str, Any]] = []
    for item in manifest["sessions"]:
        archived = Path(item["archive_file"])
        errors: list[str] = []
        if not archived.exists():
            errors.append("archive file missing")
        elif not archived.is_file():
            errors.append("archive path is not a file")
        else:
            actual_size = archived.stat().st_size
            if actual_size != item["size_bytes"]:
                errors.append("size mismatch")
            actual_hash = sha256_file(archived)
            if actual_hash != item["sha256"]:
                errors.append("sha256 mismatch")
        results.append(
            {
                "source_file": item["source_file"],
                "archive_file": item["archive_file"],
                "status": "failed" if errors else "ok",
                "errors": errors,
            }
        )
    ok = sum(1 for item in results if item["status"] == "ok")
    return {
        "report_type": "session_archive_verify",
        "manifest_file": str(manifest_file.expanduser().resolve()),
        "summary": {
            "ok": ok,
            "failed": len(results) - ok,
            "checked": len(results),
        },
        "sessions": results,
    }


def prune_local_sessions(
    *,
    manifest_file: Path,
    confirm_prune_local: bool,
) -> dict[str, Any]:
    if not confirm_prune_local:
        raise ValueError("pass --confirm-prune-local to delete verified local session files")
    verify = verify_archive(manifest_file)
    if verify["summary"]["failed"] > 0:
        raise ValueError("archive verification failed; refusing to prune local sessions")
    manifest = load_manifest(manifest_file)
    session_root = Path(manifest["session_root"]).expanduser().resolve()
    results: list[dict[str, Any]] = []
    for item in manifest["sessions"]:
        source = Path(item["source_file"])
        require_source_inside_session_root(source, session_root)
        if not source.exists():
            status = "missing"
        else:
            source.unlink()
            status = "deleted"
        results.append(
            {
                "source_file": str(source),
                "archive_file": item["archive_file"],
                "status": status,
            }
        )
    return {
        "report_type": "session_archive_prune",
        "manifest_file": str(manifest_file.expanduser().resolve()),
        "summary": {
            "deleted_count": sum(1 for item in results if item["status"] == "deleted"),
            "missing_count": sum(1 for item in results if item["status"] == "missing"),
        },
        "sessions": results,
    }


def session_record(path: Path, session_root: Path) -> dict[str, Any]:
    project = ""
    session_id = ""
    first_timestamp = ""
    last_timestamp = ""
    for _line_no, _raw, record in iter_jsonl(path):
        ts = record_timestamp(record)
        if ts and not first_timestamp:
            first_timestamp = ts
        if ts:
            last_timestamp = ts
        if record.get("type") in {"session_meta", "turn_context"}:
            project = project or extract_project(record)
            session_id = session_id or extract_session_id(record)
        if project and session_id and last_timestamp:
            continue
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    activity_at = last_timestamp or mtime
    return {
        "source_file": str(path.resolve()),
        "source_relative_path": str(path.resolve().relative_to(session_root)),
        "project": project or str(path.parent),
        "session_id": session_id,
        "size_bytes": stat.st_size,
        "mtime": mtime,
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
        "activity_at": activity_at,
    }


def matches_project(candidate: dict[str, Any], project: str | None) -> bool:
    if not project:
        return True
    return candidate["project"].rstrip("/\\") == project.rstrip("/\\")


def require_archive_root_outside_session_root(archive_root: Path, session_root: Path) -> None:
    try:
        archive_root.relative_to(session_root)
    except ValueError:
        return
    raise ValueError("archive root must be outside the session root")


def require_session_root(session_root: Path) -> None:
    if not session_root.exists():
        raise ValueError(f"session root does not exist: {session_root}")
    if not session_root.is_dir():
        raise ValueError(f"session root is not a directory: {session_root}")


def require_source_inside_session_root(source: Path, session_root: Path) -> None:
    try:
        source.expanduser().resolve().relative_to(session_root)
    except ValueError as exc:
        raise ValueError(
            f"source file is outside the manifest session root: {source}"
        ) from exc


def load_manifest(manifest_file: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_file.expanduser().read_text(encoding="utf-8"))
    if manifest.get("type") != MANIFEST_TYPE:
        raise ValueError("manifest is not a codex session archive manifest")
    if manifest.get("version") != MANIFEST_VERSION:
        raise ValueError(f"unsupported archive manifest version: {manifest.get('version')}")
    sessions = manifest.get("sessions")
    if not isinstance(sessions, list):
        raise ValueError("manifest sessions must be a list")
    return manifest


def write_manifest(manifest: dict[str, Any]) -> None:
    path = Path(manifest["manifest_file"])
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def write_markdown_manifest(manifest: dict[str, Any]) -> None:
    path = Path(manifest["archive_dir"]) / "manifest.md"
    lines = [
        "# Codex Session Archive",
        "",
        f"Project: `{manifest['project'] or 'all projects'}`",
        f"Session root: `{manifest['session_root']}`",
        f"Archived sessions: {format_count(manifest['summary']['archived_count'])}",
        f"Archived bytes: {format_bytes(manifest['summary']['total_bytes'], 'both')}",
        "",
        "| Session | Size | Source | Archive |",
        "| --- | ---: | --- | --- |",
    ]
    for item in manifest["sessions"]:
        lines.append(
            "| "
            f"`{item['session_id'] or 'not recorded'}` | "
            f"{format_bytes(item['size_bytes'], 'both')} | "
            f"`{item['source_file']}` | "
            f"`{item['archive_relative_path']}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return parse_timestamp(value)


def parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_duration(value: str) -> timedelta:
    match = re.fullmatch(r"(\d+)([dhm])", value.strip().lower())
    if not match:
        raise ValueError("duration must look like 30d, 12h, or 90m")
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(minutes=amount)


def parse_size(value: str) -> int:
    match = re.fullmatch(r"(\d+)(?:\s*([kmgt]?i?b|b))?", value.strip().lower())
    if not match:
        raise ValueError("size must look like 100MiB, 1GiB, 500KB, or 1024")
    amount = int(match.group(1))
    unit = match.group(2) or "b"
    multipliers = {
        "b": 1,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
    }
    return amount * multipliers[unit]


def default_archive_name(project: str | None) -> str:
    project_slug = slugify(project or "all-projects")
    return f"{project_slug}-{now_stamp()}"


def slugify(value: str) -> str:
    base = value.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1] or "project"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-._")
    return slug or "project"


def format_plan(result: dict[str, Any]) -> str:
    lines = [
        "Codex Session Archive Plan",
        f"Session root: {result['session_root']}",
        f"Project: {result['project'] or 'all projects'}",
        (
            "Candidates: "
            f"{format_count(result['summary']['candidate_count'])}, "
            f"{format_bytes(result['summary']['total_bytes'], 'both')}"
        ),
    ]
    for item in result["candidates"]:
        lines.append(
            f"- {format_bytes(item['size_bytes'], 'both')} "
            f"{item['session_id'] or 'not recorded'} {item['source_file']}"
        )
    return "\n".join(lines)


def format_archive(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Codex Session Archive",
            f"Archive: {result['archive_dir']}",
            f"Manifest: {result['manifest_file']}",
            (
                "Archived: "
                f"{format_count(result['summary']['archived_count'])}, "
                f"{format_bytes(result['summary']['total_bytes'], 'both')}"
            ),
        ]
    )


def format_verify(result: dict[str, Any]) -> str:
    lines = [
        "Codex Session Archive Verification",
        f"Manifest: {result['manifest_file']}",
        f"OK: {format_count(result['summary']['ok'])}",
        f"Failed: {format_count(result['summary']['failed'])}",
    ]
    for item in result["sessions"]:
        if item["status"] == "failed":
            lines.append(f"- FAILED {item['archive_file']}: {'; '.join(item['errors'])}")
    return "\n".join(lines)


def format_prune(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Codex Session Local Prune",
            f"Manifest: {result['manifest_file']}",
            f"Deleted: {format_count(result['summary']['deleted_count'])}",
            f"Already missing: {format_count(result['summary']['missing_count'])}",
        ]
    )
