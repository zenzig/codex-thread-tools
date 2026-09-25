"""Archive Codex and Claude Code session files to external storage with manifests."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from typing import Any

from agent_thread_tools.display import format_bytes, format_count
from agent_thread_tools.sessionlib import (
    iter_session_records,
    now_iso,
    now_stamp,
    record_timestamp,
    sha256_file,
)
from agent_thread_tools.archive_paths import ArchivePathError, resolve_archive_member
from agent_thread_tools.atomic_directory import staged_directory, target_reservation
from agent_thread_tools.sessionpaths import (
    claude_session_root,
    companion_dir,
    companion_files,
    iter_session_paths,
)
from agent_thread_tools.thread_health import extract_project, extract_session_id


MANIFEST_TYPE = "codex_session_archive_manifest"
MANIFEST_VERSION = 1


def build_archive_plan(
    *,
    session_root: Path,
    project: str | None,
    older_than: str | None,
    min_size: str | None,
    now: str | None = None,
    open_session_ids: set[str] | None = None,
    agent: str | None = None,
) -> dict[str, Any]:
    resolved_root = session_root.expanduser().resolve()
    require_session_root(resolved_root)
    open_session_ids = open_session_ids or set()
    now_dt = parse_now(now)
    min_size_bytes = parse_size(min_size or "0")
    cutoff = (
        now_dt - parse_duration(older_than)
        if older_than
        else None
    )
    candidates = []
    skipped_open: list[str] = []
    for path in sorted(iter_session_paths(resolved_root)):
        if not path.is_file():
            continue
        # Claude Code names each session file after its session id.
        if path.stem in open_session_ids:
            skipped_open.append(str(path))
            continue
        candidates.append(session_record(path, resolved_root))
    candidates = [
        candidate
        for candidate in candidates
        if matches_project(candidate, project)
        and candidate["total_bytes"] >= min_size_bytes
        and (cutoff is None or parse_timestamp(candidate["activity_at"]) < cutoff)
    ]
    return {
        "report_type": "session_archive_plan",
        "agent": agent or agent_for_root(resolved_root),
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
            "total_bytes": sum(candidate["total_bytes"] for candidate in candidates),
            "skipped_open_count": len(skipped_open),
        },
        "candidates": candidates,
        "skipped_open": skipped_open,
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
    open_session_ids: set[str] | None = None,
    agent: str | None = None,
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
        open_session_ids=open_session_ids,
        agent=agent,
    )
    container_name = f"{plan['agent']}-session-archives"
    if archive_name is None:
        archive_name = default_archive_name(project)
    else:
        archive_name = validate_archive_name(archive_name)
    archive_container = archive_root.expanduser() / container_name
    if archive_container.is_symlink():
        raise ValueError("archive container is a symlink")
    archive_dir = resolved_archive_root / container_name / archive_name

    with staged_directory(archive_dir, replace=force) as staging_dir:
        archived: list[dict[str, Any]] = []
        for candidate in plan["candidates"]:
            companions = candidate.pop("companions")
            archived.append(_copy_verified(candidate, staging_dir, archive_dir))
            # A Claude Code session's folder (subagents, tool results) travels with it.
            for companion in companions:
                entry = _copy_verified(companion, staging_dir, archive_dir)
                entry["companion_of"] = candidate["source_file"]
                archived.append(entry)

        manifest = {
            "type": MANIFEST_TYPE,
            "version": MANIFEST_VERSION,
            "agent": plan["agent"],
            "created_at": now_iso(),
            "session_root": str(resolved_session_root),
            "archive_root": str(resolved_archive_root),
            "archive_dir": str(archive_dir),
            "manifest_file": str(archive_dir / "manifest.json"),
            "project": project or "",
            "selection": plan["selection"],
            "summary": {
                "archived_count": sum(1 for item in archived if "companion_of" not in item),
                "file_count": len(archived),
                "total_bytes": sum(item["size_bytes"] for item in archived),
            },
            "sessions": archived,
        }
        write_manifest(manifest, path=staging_dir / "manifest.json")
        write_markdown_manifest(manifest, path=staging_dir / "manifest.md")
        return manifest


def verify_archive(manifest_file: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_file)
    archive_dir = manifest_file.expanduser().resolve().parent
    results: list[dict[str, Any]] = []
    for item in manifest["sessions"]:
        archive_relative_path = item.get("archive_relative_path")
        if not isinstance(archive_relative_path, str):
            archive_relative_path = ""
        errors: list[str] = []
        try:
            archived = resolve_archive_member(archive_dir, archive_relative_path)
        except ArchivePathError as exc:
            errors.append(str(exc))
        else:
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
                "archive_relative_path": archive_relative_path,
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
    open_session_ids: set[str] | None = None,
) -> dict[str, Any]:
    resolved_manifest = manifest_file.expanduser().resolve()
    with target_reservation(resolved_manifest.parent):
        return _prune_local_sessions_locked(
            manifest_file=resolved_manifest,
            confirm_prune_local=confirm_prune_local,
            open_session_ids=open_session_ids or set(),
        )


def _prune_local_sessions_locked(
    *,
    manifest_file: Path,
    confirm_prune_local: bool,
    open_session_ids: set[str],
) -> dict[str, Any]:
    if not confirm_prune_local:
        raise ValueError("pass --confirm-prune-local to delete verified local session files")
    verify = verify_archive(manifest_file)
    if verify["summary"]["failed"] > 0:
        raise ValueError("archive verification failed; refusing to prune local sessions")
    manifest = load_manifest(manifest_file)
    session_root = Path(manifest["session_root"]).expanduser().resolve()
    results: list[dict[str, Any]] = []
    staged_entries: list[tuple[Path, Path, dict[str, Any], dict[str, Any]]] = []
    validation_failed = False
    quarantine_root = session_root / f".codex-thread-tools-prune-{uuid4().hex}"

    def staged_path(source: Path) -> Path:
        return quarantine_root / source.resolve().relative_to(session_root)

    for item in manifest["sessions"]:
        source = Path(item["source_file"])
        result = {
            "source_file": str(source),
            "archive_file": item["archive_file"],
            "status": "missing",
        }

        if not source.exists():
            results.append(result)
            continue

        try:
            require_source_inside_session_root(source, session_root)
            if not source.is_file():
                raise ValueError("source file is not a regular file")
            owner = Path(item.get("companion_of") or source)
            if owner.stem in open_session_ids:
                raise ValueError("session is open in Claude Code; close it before pruning")
            _assert_source_matches_plan(source, item, compare_identity=False)
            staged_target = staged_path(source)
            staged_target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(staged_target)
            result["status"] = "ready"
            staged_entries.append((source, staged_target, result, item))
        except Exception as exc:
            validation_failed = True
            result["status"] = "failed"
            result["error"] = str(exc)
        results.append(result)

    if validation_failed:
        _rollback_prune_staging(staged_entries, quarantine_root)
        return {
            "report_type": "session_archive_prune",
            "manifest_file": str(manifest_file.expanduser().resolve()),
            "summary": {
                "deleted_count": 0,
                "missing_count": sum(1 for item in results if item["status"] == "missing"),
                "failed_count": _failed_prune_count(results),
            },
            "sessions": results,
        }

    for source, staged_target, result, item in staged_entries:
        try:
            _assert_source_matches_plan(staged_target, item, compare_identity=False)
        except Exception as exc:
            validation_failed = True
            result["status"] = "failed"
            result["error"] = str(exc)
            break

    if validation_failed:
        _rollback_prune_staging(staged_entries, quarantine_root)
        return {
            "report_type": "session_archive_prune",
            "manifest_file": str(manifest_file.expanduser().resolve()),
            "summary": {
                "deleted_count": 0,
                "missing_count": sum(1 for item in results if item["status"] == "missing"),
                "failed_count": _failed_prune_count(results),
            },
            "sessions": results,
        }

    for _source, staged_target, result, _item in staged_entries:
        try:
            staged_target.unlink()
            result["status"] = "deleted"
        except OSError as exc:
            result["status"] = "failed"
            result["error"] = f"failed to delete quarantined source: {exc}"
            _restore_pruned_source(_source, staged_target, result)
    _remove_empty_directories(quarantine_root)
    for item in manifest["sessions"]:
        if "companion_of" not in item:
            _remove_empty_directories(companion_dir(Path(item["source_file"])))
    return {
        "report_type": "session_archive_prune",
        "manifest_file": str(manifest_file.expanduser().resolve()),
        "summary": {
            "deleted_count": sum(1 for item in results if item["status"] == "deleted"),
            "missing_count": sum(1 for item in results if item["status"] == "missing"),
            "failed_count": _failed_prune_count(results),
        },
        "sessions": results,
    }


def session_record(path: Path, session_root: Path) -> dict[str, Any]:
    project = ""
    session_id = ""
    first_timestamp = ""
    last_timestamp = ""
    for _line_no, _raw, record in iter_session_records(path):
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
    record = file_record(path, session_root)
    companions = [file_record(companion, session_root) for companion in companion_files(path)]
    return {
        **record,
        "project": project or str(path.parent),
        "session_id": session_id,
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
        "activity_at": last_timestamp or record["mtime"],
        "companion_count": len(companions),
        "total_bytes": record["size_bytes"] + sum(item["size_bytes"] for item in companions),
        "companions": companions,
    }


def file_record(path: Path, session_root: Path) -> dict[str, Any]:
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "source_file": str(path.resolve()),
        "source_relative_path": str(path.resolve().relative_to(session_root)),
        "size_bytes": stat.st_size,
        "source_sha256": sha256_file(path),
        "source_dev": stat.st_dev,
        "source_inode": stat.st_ino,
        "source_mtime_ns": stat.st_mtime_ns,
        "mtime": mtime,
    }


def agent_for_root(session_root: Path) -> str:
    """Codex keeps sessions under year folders; Claude Code under project folders."""
    if session_root == claude_session_root().resolve():
        return "claude"
    if not session_root.is_dir():
        return "codex"
    folders = [
        path.name
        for path in session_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ]
    if folders and not all(name.isdigit() for name in folders):
        return "claude"
    return "codex"


def _copy_verified(
    candidate: dict[str, Any],
    staging_dir: Path,
    archive_dir: Path,
) -> dict[str, Any]:
    source = Path(candidate["source_file"])
    _assert_source_matches_plan(source, candidate, compare_identity=True)
    relative_path = Path("sessions") / candidate["source_relative_path"]
    destination = staging_dir / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    try:
        _assert_source_matches_plan(source, candidate, compare_identity=True)
    except RuntimeError as exc:
        raise RuntimeError(f"session file changed while copying: {exc}") from exc
    source_size = source.stat().st_size
    source_sha256 = sha256_file(source)
    if source_size != destination.stat().st_size:
        raise RuntimeError("session file changed while copying: size mismatch")
    archive_sha256 = sha256_file(destination)
    if source_sha256 != archive_sha256:
        raise RuntimeError("session file changed while copying: hash mismatch")
    return {
        **candidate,
        "source_sha256": candidate["source_sha256"],
        "archive_file": str(archive_dir / relative_path),
        "archive_relative_path": str(relative_path),
        "size_bytes": source_size,
        "sha256": archive_sha256,
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
    if not isinstance(manifest, dict):
        raise ValueError("manifest root must be an object")
    if manifest.get("type") != MANIFEST_TYPE:
        raise ValueError("manifest is not a codex session archive manifest")
    if manifest.get("version") != MANIFEST_VERSION:
        raise ValueError(f"unsupported archive manifest version: {manifest.get('version')}")
    sessions = manifest.get("sessions")
    if not isinstance(sessions, list):
        raise ValueError("manifest sessions must be a list")
    for index, item in enumerate(sessions):
        if not isinstance(item, dict):
            raise ValueError(f"manifest session entry {index} must be an object")
        required_strings = (
            "source_file",
            "archive_file",
            "archive_relative_path",
            "sha256",
        )
        for field in required_strings:
            if not isinstance(item.get(field), str) or not item[field]:
                raise ValueError(
                    f"manifest session entry {index} has invalid {field}"
                )
        if not isinstance(item.get("size_bytes"), int) or item["size_bytes"] < 0:
            raise ValueError(
                f"manifest session entry {index} has invalid size_bytes"
            )
    return manifest


def write_manifest(manifest: dict[str, Any], *, path: Path | None = None) -> None:
    path = path or Path(manifest["manifest_file"])
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def write_markdown_manifest(manifest: dict[str, Any], *, path: Path | None = None) -> None:
    path = path or Path(manifest["archive_dir"]) / "manifest.md"
    lines = [
        "# Session Archive",
        "",
        f"Project: `{manifest['project'] or 'all projects'}`",
        f"Agent: {manifest.get('agent', 'codex')}",
        f"Session root: `{manifest['session_root']}`",
        f"Archived sessions: {format_count(manifest['summary']['archived_count'])}",
        f"Archived files: {format_count(manifest['summary'].get('file_count', manifest['summary']['archived_count']))}",
        f"Archived bytes: {format_bytes(manifest['summary']['total_bytes'], 'both')}",
        "",
        "| Session | Size | Source | Archive |",
        "| --- | ---: | --- | --- |",
    ]
    for item in manifest["sessions"]:
        lines.append(
            "| "
            f"`{item.get('session_id') or 'not recorded'}` | "
            f"{format_bytes(item['size_bytes'], 'both')} | "
            f"`{item['source_file']}` | "
            f"`{item['archive_relative_path']}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_archive_name(name: str) -> str:
    if not name:
        raise ValueError("unsafe archive name: must be a non-empty path component")
    if name in {".", ".."}:
        raise ValueError("unsafe archive name")
    if Path(name).is_absolute():
        raise ValueError("unsafe archive name")
    if name == Path(name).name:
        if re.fullmatch(r"[^\x00-\x1f\x7f/\\\\]+", name):
            return name
    raise ValueError("unsafe archive name")


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
    project_slug = session_archive_slug(project or "all-projects")
    return f"{project_slug}-{now_stamp()}"


def session_archive_slug(value: str) -> str:
    base = value.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1] or "project"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-._")
    return slug or "project"


def format_plan(result: dict[str, Any]) -> str:
    lines = [
        "Session Archive Plan",
        f"Agent: {result['agent']}",
        f"Session root: {result['session_root']}",
        f"Project: {result['project'] or 'all projects'}",
        (
            "Candidates: "
            f"{format_count(result['summary']['candidate_count'])}, "
            f"{format_bytes(result['summary']['total_bytes'], 'both')}"
        ),
    ]
    if result["summary"].get("skipped_open_count"):
        lines.append(
            "Skipped (open in Claude Code): "
            f"{format_count(result['summary']['skipped_open_count'])}"
        )
    for item in result["candidates"]:
        extra = f" (+{format_count(item['companion_count'])} files)" if item.get("companion_count") else ""
        lines.append(
            f"- {format_bytes(item['total_bytes'], 'both')} "
            f"{item['session_id'] or 'not recorded'} {item['source_file']}{extra}"
        )
    return "\n".join(lines)


def format_archive(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Session Archive",
            f"Archive: {result['archive_dir']}",
            f"Manifest: {result['manifest_file']}",
            (
                "Archived: "
                f"{format_count(result['summary']['archived_count'])} sessions, "
                f"{format_count(result['summary'].get('file_count', result['summary']['archived_count']))} files, "
                f"{format_bytes(result['summary']['total_bytes'], 'both')}"
            ),
        ]
    )


def format_verify(result: dict[str, Any]) -> str:
    lines = [
        "Session Archive Verification",
        f"Manifest: {result['manifest_file']}",
        f"OK: {format_count(result['summary']['ok'])}",
        f"Failed: {format_count(result['summary']['failed'])}",
    ]
    for item in result["sessions"]:
        if item["status"] == "failed":
            lines.append(f"- FAILED {item['archive_file']}: {'; '.join(item['errors'])}")
    return "\n".join(lines)


def format_prune(result: dict[str, Any]) -> str:
    lines = [
        "Session Local Prune",
        f"Manifest: {result['manifest_file']}",
        f"Deleted: {format_count(result['summary']['deleted_count'])}",
        f"Failed: {format_count(result['summary'].get('failed_count', 0))}",
        f"Already missing: {format_count(result['summary']['missing_count'])}",
    ]
    for item in result["sessions"]:
        if item["status"] == "failed":
            lines.append(f"FAILED {item['source_file']}: {item.get('error', '')}")
            if item.get("recovery_file"):
                lines.append(f"  Recovery: {item['recovery_file']}")
        elif item["status"] == "restored" and item.get("error"):
            lines.append(f"RESTORED {item['source_file']}: {item['error']}")
    return "\n".join(lines)


def _assert_source_matches_plan(
    source: Path,
    item: dict[str, Any],
    *,
    compare_identity: bool,
) -> None:
    source_stat = source.stat()
    size_bytes = item.get("size_bytes")
    if not isinstance(size_bytes, int):
        raise ValueError("source size is missing from manifest")

    if compare_identity:
        source_dev = item.get("source_dev")
        source_inode = item.get("source_inode")
        if isinstance(source_dev, int) and source_stat.st_dev != source_dev:
            raise RuntimeError("source identity changed: device changed")
        if isinstance(source_inode, int) and source_stat.st_ino != source_inode:
            raise RuntimeError("source identity changed: inode changed")

    if source_stat.st_size != size_bytes:
        raise RuntimeError("session source metadata changed: size mismatch")

    source_sha = item.get("source_sha256", item.get("sha256"))
    if source_sha is not None:
        if not isinstance(source_sha, str) or not source_sha:
            raise RuntimeError("source hash is missing from manifest")
        if sha256_file(source) != source_sha:
            raise RuntimeError("session source metadata changed: hash mismatch")

    if not compare_identity:
        return


def _rollback_prune_staging(
    staged_entries: list[tuple[Path, Path, dict[str, Any], dict[str, Any]]],
    quarantine_root: Path,
) -> None:
    for source, staged_target, result, _item in reversed(staged_entries):
        _restore_pruned_source(source, staged_target, result)
    _remove_empty_directories(quarantine_root)


def _restore_pruned_source(source: Path, staged_target: Path, result: dict[str, Any]) -> None:
    if not staged_target.exists():
        return
    if source.exists():
        _append_prune_error(
            result,
            "a new file exists at the original path; archived source retained "
            "in recovery quarantine",
        )
        result["status"] = "failed"
        result["recovery_file"] = str(staged_target)
        return
    try:
        staged_target.rename(source)
        result["status"] = "restored"
        result.pop("recovery_file", None)
    except OSError as exc:
        _append_prune_error(result, f"failed to restore staged source: {exc}")
        result["status"] = "failed"
        result["recovery_file"] = str(staged_target)


def _append_prune_error(result: dict[str, Any], message: str) -> None:
    existing = result.get("error")
    result["error"] = f"{existing}; {message}" if existing else message


def _failed_prune_count(results: list[dict[str, Any]]) -> int:
    return sum(
        1
        for item in results
        if item["status"] == "failed" or item.get("error") is not None
    )


def _remove_empty_directories(root: Path) -> None:
    if not root.exists():
        return
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass
