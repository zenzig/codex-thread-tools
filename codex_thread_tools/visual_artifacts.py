"""Visual artifact detection and archiving for Codex session JSONL files."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codex_thread_tools.sessionlib import iter_jsonl, now_iso, record_timestamp
from codex_thread_tools.sessionpaths import default_session_root


LOCAL_MEDIA_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".avif",
    ".bmp",
    ".svg",
    ".mp4",
    ".mov",
    ".webm",
    ".m4v",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".svg"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}

DATA_URL_RE = re.compile(
    r"data:(?P<mime>(?:image|video)/[A-Za-z0-9.+-]+);base64,(?P<data>[^\s)'\">]+)"
)
MARKDOWN_MEDIA_RE = re.compile(r"!\[[^\]]*\]\((?P<path>[^)]+)\)")
ABSOLUTE_MEDIA_PATH_RE = re.compile(
    r"(?P<path>/[^\n\r`'\"<>]*(?:"
    + "|".join(re.escape(ext) for ext in sorted(LOCAL_MEDIA_EXTENSIONS, key=len, reverse=True))
    + r"))"
)
REMOTE_MEDIA_RE = re.compile(
    r"https?://[^\s)'\">]+(?:"
    + "|".join(re.escape(ext) for ext in sorted(LOCAL_MEDIA_EXTENSIONS, key=len, reverse=True))
    + r")(?:\?[^\s)'\">]+)?"
)


@dataclass(frozen=True)
class VisualSource:
    line_no: int
    timestamp: str
    record_type: str
    payload_path: str
    source_kind: str
    original_ref: str


@dataclass
class VisualOccurrence:
    artifact_id: str
    status: str
    media_kind: str
    mime: str
    extension: str
    sha256: str
    bytes: int
    source: VisualSource
    data: bytes | None = None
    local_path: Path | None = None
    archive_path: str = ""
    error: str = ""

    def to_manifest(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "status": self.status,
            "media_kind": self.media_kind,
            "mime": self.mime,
            "extension": self.extension,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "archive_path": self.archive_path,
            "source": {
                "line_no": self.source.line_no,
                "timestamp": self.source.timestamp,
                "record_type": self.source.record_type,
                "payload_path": self.source.payload_path,
                "source_kind": self.source.source_kind,
                "original_ref": truncate_ref(self.source.original_ref),
            },
            "notes": "",
            "error": self.error,
        }


def scan_session_visuals(
    session_file: Path,
    allow_local_roots: list[Path] | None = None,
) -> dict[str, Any]:
    artifacts = iter_visual_occurrences(session_file, allow_local_roots)
    return {
        "source_session": str(session_file),
        "summary": summarize_occurrences(artifacts),
        "artifacts": [artifact.to_manifest() for artifact in artifacts],
    }


def iter_visual_occurrences(
    session_file: Path,
    allow_local_roots: list[Path] | None = None,
) -> list[VisualOccurrence]:
    allow_roots = normalize_roots(allow_local_roots)
    artifacts: list[VisualOccurrence] = []
    for line_no, _raw, record in iter_jsonl(session_file):
        artifacts.extend(scan_record_visuals(record, line_no, allow_roots))
    for index, artifact in enumerate(artifacts, 1):
        artifact.artifact_id = f"artifact-{index:03d}"
    return artifacts


def scan_record_visuals(
    record: dict[str, Any],
    line_no: int,
    allow_local_roots: list[Path] | None = None,
) -> list[VisualOccurrence]:
    allow_roots = normalize_roots(allow_local_roots)
    source_base = {
        "line_no": line_no,
        "timestamp": record_timestamp(record),
        "record_type": str(record.get("type", "")),
    }
    artifacts: list[VisualOccurrence] = []
    scan_value(record.get("payload"), "payload", source_base, allow_roots, artifacts)
    return artifacts


def scan_record_visual_metrics(record: dict[str, Any]) -> dict[str, int]:
    metrics = {
        "visual_artifacts": 0,
        "visual_embedded_artifacts": 0,
        "visual_local_references": 0,
        "visual_video_artifacts": 0,
        "visual_embedded_bytes": 0,
        "largest_visual_artifact_bytes": 0,
        "visual_artifact_errors": 0,
        "visual_artifact_skipped": 0,
    }
    update_value_visual_metrics(record.get("payload"), metrics)
    return metrics


def update_value_visual_metrics(value: Any, metrics: dict[str, int]) -> None:
    if isinstance(value, dict):
        for nested in value.values():
            update_value_visual_metrics(nested, metrics)
    elif isinstance(value, list):
        for nested in value:
            update_value_visual_metrics(nested, metrics)
    elif isinstance(value, str):
        update_string_visual_metrics(value, metrics)


def update_string_visual_metrics(value: str, metrics: dict[str, int]) -> None:
    occupied_spans: list[tuple[int, int]] = []
    for match in DATA_URL_RE.finditer(value):
        occupied_spans.append(match.span())
        mime = match.group("mime")
        estimated_bytes = estimate_base64_bytes(match.group("data"))
        metrics["visual_artifacts"] += 1
        metrics["visual_embedded_artifacts"] += 1
        metrics["visual_embedded_bytes"] += estimated_bytes
        metrics["largest_visual_artifact_bytes"] = max(
            metrics["largest_visual_artifact_bytes"],
            estimated_bytes,
        )
        if media_kind_for_mime(mime) == "video":
            metrics["visual_video_artifacts"] += 1
        if estimated_bytes == 0:
            metrics["visual_artifact_errors"] += 1
    for match in MARKDOWN_MEDIA_RE.finditer(value):
        ref = match.group("path").strip()
        occupied_spans.append(match.span())
        if local_or_remote_media_ref(ref):
            metrics["visual_artifacts"] += 1
            if video_ref(ref):
                metrics["visual_video_artifacts"] += 1
            if ref.startswith("http://") or ref.startswith("https://"):
                metrics["visual_artifact_skipped"] += 1
            elif ref.startswith("/"):
                metrics["visual_local_references"] += 1
    for match in REMOTE_MEDIA_RE.finditer(value):
        if not span_is_occupied(match.span(), occupied_spans):
            metrics["visual_artifacts"] += 1
            metrics["visual_artifact_skipped"] += 1
            if video_ref(match.group(0)):
                metrics["visual_video_artifacts"] += 1
    for match in ABSOLUTE_MEDIA_PATH_RE.finditer(value):
        if not span_is_occupied(match.span(), occupied_spans) and not relative_path_fragment(value, match.start()):
            metrics["visual_artifacts"] += 1
            metrics["visual_local_references"] += 1
            if video_ref(match.group("path")):
                metrics["visual_video_artifacts"] += 1


def scan_value(
    value: Any,
    payload_path: str,
    source_base: dict[str, Any],
    allow_roots: list[Path],
    artifacts: list[VisualOccurrence],
) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            scan_value(nested, f"{payload_path}.{key}", source_base, allow_roots, artifacts)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            scan_value(nested, f"{payload_path}[{index}]", source_base, allow_roots, artifacts)
    elif isinstance(value, str):
        scan_string(value, payload_path, source_base, allow_roots, artifacts)


def scan_string(
    value: str,
    payload_path: str,
    source_base: dict[str, Any],
    allow_roots: list[Path],
    artifacts: list[VisualOccurrence],
) -> None:
    occupied_spans: list[tuple[int, int]] = []
    for match in DATA_URL_RE.finditer(value):
        occupied_spans.append(match.span())
        artifacts.append(embedded_occurrence(match, payload_path, source_base))
    for match in MARKDOWN_MEDIA_RE.finditer(value):
        ref = match.group("path").strip()
        occupied_spans.append(match.span())
        add_path_or_url(ref, payload_path, source_base, allow_roots, artifacts, "markdown_media")
    for match in REMOTE_MEDIA_RE.finditer(value):
        ref = match.group(0)
        if not span_is_occupied(match.span(), occupied_spans):
            add_remote(ref, payload_path, source_base, artifacts)
    for match in ABSOLUTE_MEDIA_PATH_RE.finditer(value):
        ref = match.group("path").strip()
        if not span_is_occupied(match.span(), occupied_spans) and not relative_path_fragment(value, match.start()):
            add_path_or_url(ref, payload_path, source_base, allow_roots, artifacts, "local_path")


def span_is_occupied(span: tuple[int, int], occupied_spans: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start >= used_start and end <= used_end for used_start, used_end in occupied_spans)


def relative_path_fragment(value: str, start: int) -> bool:
    return start > 0 and value[start - 1] in {".", ":", "/"}


def embedded_occurrence(
    match: re.Match[str],
    payload_path: str,
    source_base: dict[str, Any],
) -> VisualOccurrence:
    mime = match.group("mime")
    extension = extension_for_mime(mime)
    source = source_for(payload_path, "embedded_data_url", match.group(0), source_base)
    try:
        data = base64.b64decode(match.group("data"), validate=True)
    except Exception:
        return VisualOccurrence(
            artifact_id="",
            status="error",
            media_kind=media_kind_for_mime(mime),
            mime=mime,
            extension=extension,
            sha256="",
            bytes=0,
            source=source,
            error="invalid base64 data URL",
        )
    return VisualOccurrence(
        artifact_id="",
        status="ready",
        media_kind=media_kind_for_mime(mime),
        mime=mime,
        extension=extension,
        sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data),
        source=source,
        data=data,
    )


def add_path_or_url(
    ref: str,
    payload_path: str,
    source_base: dict[str, Any],
    allow_roots: list[Path],
    artifacts: list[VisualOccurrence],
    source_kind: str,
) -> None:
    if ref.startswith("http://") or ref.startswith("https://"):
        add_remote(ref, payload_path, source_base, artifacts)
        return
    if not ref.startswith("/"):
        return
    path = Path(ref).expanduser()
    extension = path.suffix.lower()
    if extension not in LOCAL_MEDIA_EXTENSIONS:
        return
    source = source_for(payload_path, source_kind, ref, source_base)
    if not allow_roots:
        artifacts.append(
            VisualOccurrence(
                artifact_id="",
                status="skipped",
                media_kind=media_kind_for_extension(extension),
                mime=mime_for_extension(extension),
                extension=extension,
                sha256="",
                bytes=0,
                source=source,
                error="local visual file requires --allow-local-root before it can be copied",
            )
        )
        return
    if not path.exists():
        artifacts.append(
            VisualOccurrence(
                artifact_id="",
                status="error",
                media_kind=media_kind_for_extension(extension),
                mime=mime_for_extension(extension),
                extension=extension,
                sha256="",
                bytes=0,
                source=source,
                error="local visual file does not exist",
            )
        )
        return
    resolved = path.resolve()
    if allow_roots and not path_allowed(resolved, allow_roots):
        artifacts.append(
            VisualOccurrence(
                artifact_id="",
                status="skipped",
                media_kind=media_kind_for_extension(extension),
                mime=mime_for_extension(extension),
                extension=extension,
                sha256="",
                bytes=0,
                source=source,
                local_path=resolved,
                error="local visual file resolves outside allowed roots",
            )
        )
        return
    if not resolved.is_file():
        return
    try:
        size = resolved.stat().st_size
        sha256 = hash_file(resolved)
    except OSError as exc:
        artifacts.append(
            VisualOccurrence(
                artifact_id="",
                status="error",
                media_kind=media_kind_for_extension(extension),
                mime=mime_for_extension(extension),
                extension=extension,
                sha256="",
                bytes=0,
                source=source,
                local_path=resolved,
                error=f"local visual file could not be read: {exc}",
            )
        )
        return
    artifacts.append(
        VisualOccurrence(
            artifact_id="",
            status="ready",
            media_kind=media_kind_for_extension(extension),
            mime=mime_for_extension(extension),
            extension=extension,
            sha256=sha256,
            bytes=size,
            source=source,
            local_path=resolved,
        )
    )


def add_remote(
    ref: str,
    payload_path: str,
    source_base: dict[str, Any],
    artifacts: list[VisualOccurrence],
) -> None:
    extension = Path(ref.split("?", 1)[0]).suffix.lower()
    if extension not in LOCAL_MEDIA_EXTENSIONS:
        extension = ""
    artifacts.append(
        VisualOccurrence(
            artifact_id="",
            status="skipped",
            media_kind=media_kind_for_extension(extension),
            mime=mime_for_extension(extension),
            extension=extension,
            sha256="",
            bytes=0,
            source=source_for(payload_path, "remote_url", ref, source_base),
            error="remote URLs are recorded but not copied by this local archive tool",
        )
    )


def archive_visuals(
    session_file: Path,
    archive_root: Path,
    project_name: str,
    artifact_set: str,
    visual_context: str,
    allow_local_roots: list[Path] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    archive_root = archive_root.expanduser().resolve()
    validate_archive_root(archive_root)
    project_slug = slugify(project_name)
    set_slug = slugify(artifact_set)
    archive_dir = archive_root / "codex-visual-artifacts" / project_slug / set_slug
    artifacts_dir = archive_dir / "artifacts"
    artifacts = iter_visual_occurrences(session_file, allow_local_roots)

    if dry_run:
        return {
            "dry_run": True,
            "archive_dir": str(archive_dir),
            "summary": summarize_occurrences(artifacts),
            "artifacts": [artifact.to_manifest() for artifact in artifacts],
        }

    if archive_dir.exists() and not force:
        raise SystemExit(f"error: archive already exists: {archive_dir}")
    archive_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    stored: dict[str, Path] = {}
    copied_bytes = 0
    for artifact in artifacts:
        if artifact.status != "ready" or not artifact.sha256:
            continue
        target = stored.get(artifact.sha256)
        if target is None:
            target = artifacts_dir / f"{artifact.sha256}{artifact.extension}"
            if artifact.data is not None:
                atomic_write_bytes(target, artifact.data)
            elif artifact.local_path is not None:
                atomic_copy_file(artifact.local_path, target)
            stored[artifact.sha256] = target
            copied_bytes += artifact.bytes
        artifact.archive_path = str(target)
        artifact.status = "copied"

    manifest = build_manifest(
        session_file=session_file,
        archive_root=archive_root,
        archive_dir=archive_dir,
        project_name=project_name,
        artifact_set=artifact_set,
        visual_context=visual_context,
        artifacts=artifacts,
        copied_bytes=copied_bytes,
    )
    manifest_json = archive_dir / "manifest.json"
    manifest_markdown = archive_dir / "manifest.md"
    handoff_snippet = archive_dir / "handoff-snippet.md"
    atomic_write_text(manifest_json, json.dumps(manifest, indent=2) + "\n")
    atomic_write_text(manifest_markdown, manifest_to_markdown(manifest))
    atomic_write_text(handoff_snippet, manifest_to_handoff_snippet(manifest))

    return {
        "manifest_json": str(manifest_json),
        "manifest_markdown": str(manifest_markdown),
        "handoff_snippet": str(handoff_snippet),
        "archive_dir": str(archive_dir),
        "summary": manifest["summary"],
    }


def build_manifest(
    session_file: Path,
    archive_root: Path,
    archive_dir: Path,
    project_name: str,
    artifact_set: str,
    visual_context: str,
    artifacts: list[VisualOccurrence],
    copied_bytes: int,
) -> dict[str, Any]:
    summary = summarize_occurrences(artifacts)
    summary["stored_files"] = len({artifact.archive_path for artifact in artifacts if artifact.archive_path})
    summary["copied_bytes"] = copied_bytes
    return {
        "schema_version": 1,
        "created_at": now_iso(),
        "source_session": str(session_file),
        "project_name": project_name,
        "artifact_set": artifact_set,
        "visual_context": visual_context,
        "archive_root": str(archive_root),
        "archive_dir": str(archive_dir),
        "summary": summary,
        "artifacts": [artifact.to_manifest() for artifact in artifacts],
    }


def verify_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = 0
    mismatched = 0
    checked = 0
    details: list[dict[str, str]] = []
    for artifact in manifest.get("artifacts", []):
        archive_path = artifact.get("archive_path")
        if not archive_path:
            continue
        checked += 1
        path = Path(archive_path)
        if not path.is_file():
            missing += 1
            details.append({"artifact_id": artifact.get("artifact_id", ""), "path": archive_path})
            continue
        expected_bytes = artifact.get("bytes")
        expected_sha256 = artifact.get("sha256")
        actual_bytes = path.stat().st_size
        actual_sha256 = hash_file(path)
        if (
            isinstance(expected_bytes, int)
            and actual_bytes != expected_bytes
            or isinstance(expected_sha256, str)
            and expected_sha256
            and actual_sha256 != expected_sha256
        ):
            mismatched += 1
            details.append(
                {
                    "artifact_id": artifact.get("artifact_id", ""),
                    "path": archive_path,
                    "error": "archived file hash or size does not match manifest",
                }
            )
    return {
        "status": "warn" if missing or mismatched else "ok",
        "manifest": str(manifest_path),
        "checked_files": checked,
        "missing_files": missing,
        "mismatched_files": mismatched,
        "details": details,
    }


def summarize_occurrences(artifacts: list[VisualOccurrence]) -> dict[str, int]:
    return {
        "occurrences": len(artifacts),
        "ready": sum(1 for artifact in artifacts if artifact.status == "ready"),
        "embedded": sum(1 for artifact in artifacts if artifact.source.source_kind == "embedded_data_url"),
        "local_files": sum(
            1
            for artifact in artifacts
            if artifact.source.source_kind in {"local_path", "markdown_media"}
            and artifact.status in {"ready", "copied"}
        ),
        "videos": sum(1 for artifact in artifacts if artifact.media_kind == "video"),
        "embedded_bytes": sum(
            artifact.bytes
            for artifact in artifacts
            if artifact.source.source_kind == "embedded_data_url"
        ),
        "largest_bytes": max((artifact.bytes for artifact in artifacts), default=0),
        "errors": sum(1 for artifact in artifacts if artifact.status == "error"),
        "skipped": sum(1 for artifact in artifacts if artifact.status == "skipped"),
        "stored_files": 0,
        "copied_bytes": 0,
    }


def manifest_to_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        f"# Visual Artifact Archive - {manifest['project_name']}",
        "",
        f"Source session: `{manifest['source_session']}`",
        f"Archive directory: `{manifest['archive_dir']}`",
        "",
        "## Visual Context",
        "",
        manifest.get("visual_context") or "No visual context note provided.",
        "",
        "## Artifacts",
        "",
    ]
    for artifact in manifest.get("artifacts", []):
        lines.append(
            f"- `{artifact['artifact_id']}`: {artifact['media_kind']} {artifact['mime']}, "
            f"{artifact['bytes']} bytes, {artifact['status']}"
        )
        if artifact.get("archive_path"):
            lines.append(f"  - Archived file: `{artifact['archive_path']}`")
        lines.append(
            "  - Source: "
            f"line {artifact['source']['line_no']}, `{artifact['source']['record_type']}`, "
            f"`{artifact['source']['payload_path']}`"
        )
        if artifact.get("error"):
            lines.append(f"  - Note: {artifact['error']}")
    return "\n".join(lines).rstrip() + "\n"


def manifest_to_handoff_snippet(manifest: dict[str, Any]) -> str:
    lines = [
        "## Archived Visual References",
        "",
        f"- Visual archive manifest: `{manifest['archive_dir']}/manifest.md`",
        f"- Archive JSON: `{manifest['archive_dir']}/manifest.json`",
        "- Key visual artifacts:",
    ]
    copied = [artifact for artifact in manifest.get("artifacts", []) if artifact.get("archive_path")]
    if not copied:
        lines.append("  - No local visual artifacts were archived.")
    for artifact in copied[:10]:
        lines.append(
            f"  - `{artifact['archive_path']}`: {manifest.get('visual_context') or artifact['media_kind']}"
        )
    lines.extend(
        [
            "",
            "When continuing in a new Codex thread, load the manifest first and use the archived image/video paths as the source of truth for visual design context. Do not rely on the prior thread transcript for visual details.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def validate_archive_root(archive_root: Path) -> None:
    live_root = default_session_root().resolve()
    if archive_root == live_root or live_root in archive_root.parents:
        raise SystemExit(
            f"error: archive root must not be inside the live Codex session root: {archive_root}"
        )
    if not archive_root.exists():
        raise SystemExit(f"error: archive root does not exist: {archive_root}")
    if not archive_root.is_dir():
        raise SystemExit(f"error: archive root is not a directory: {archive_root}")


def source_for(
    payload_path: str,
    source_kind: str,
    original_ref: str,
    source_base: dict[str, Any],
) -> VisualSource:
    return VisualSource(
        line_no=int(source_base["line_no"]),
        timestamp=str(source_base["timestamp"]),
        record_type=str(source_base["record_type"]),
        payload_path=payload_path,
        source_kind=source_kind,
        original_ref=original_ref,
    )


def normalize_roots(roots: list[Path] | None) -> list[Path]:
    if not roots:
        return []
    return [root.expanduser().resolve() for root in roots]


def path_allowed(path: Path, allow_roots: list[Path]) -> bool:
    for root in allow_roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        tmp = Path(handle.name)
        handle.write(data)
    tmp.replace(path)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
        tmp = Path(handle.name)
    try:
        shutil.copy2(source, tmp)
        tmp.replace(target)
    finally:
        if tmp.exists():
            tmp.unlink()


def media_kind_for_mime(mime: str) -> str:
    if mime.startswith("video/"):
        return "video"
    return "image"


def media_kind_for_extension(extension: str) -> str:
    if extension in VIDEO_EXTENSIONS:
        return "video"
    return "image"


def estimate_base64_bytes(value: str) -> int:
    compact = "".join(value.split())
    try:
        return len(base64.b64decode(compact, validate=True))
    except Exception:
        return 0


def local_or_remote_media_ref(value: str) -> bool:
    if value.startswith("http://") or value.startswith("https://"):
        suffix = Path(value.split("?", 1)[0]).suffix.lower()
    else:
        suffix = Path(value).suffix.lower()
    return suffix in LOCAL_MEDIA_EXTENSIONS


def video_ref(value: str) -> bool:
    suffix = Path(value.split("?", 1)[0]).suffix.lower()
    return suffix in VIDEO_EXTENSIONS


def mime_for_extension(extension: str) -> str:
    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".avif": "image/avif",
        ".bmp": "image/bmp",
        ".svg": "image/svg+xml",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".m4v": "video/mp4",
    }
    return mapping.get(extension, "application/octet-stream")


def extension_for_mime(mime: str) -> str:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/avif": ".avif",
        "image/bmp": ".bmp",
        "image/svg+xml": ".svg",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
    }
    return mapping.get(mime, ".bin")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "untitled"


def truncate_ref(value: str, limit: int = 160) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "..."
