"""Local sidecar markers for completed Codex thread handoffs."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codex_thread_tools.sessionlib import iter_jsonl


MARKER_TYPE = "handoff_completed"
PROMPT_HEADER = "Codex thread handoff marker:"
DEFAULT_MARKER_FILE = Path.home() / ".codex" / "thread-tools" / "handoff-markers.jsonl"


def default_marker_file() -> Path:
    override = os.environ.get("CODEX_THREAD_HANDOFF_MARKER_FILE")
    if override:
        return Path(override).expanduser()
    return DEFAULT_MARKER_FILE


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_handoff_markers(marker_file: Path | None = None) -> list[dict[str, Any]]:
    path = marker_file or default_marker_file()
    if not path.exists():
        return []

    markers: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        marker = normalize_marker(record)
        if marker is not None:
            markers.append(marker)
    return markers


def normalize_marker(record: dict[str, Any]) -> dict[str, Any] | None:
    if record.get("type") != MARKER_TYPE:
        return None
    project = _string(record.get("project"))
    source_session_id = _string(record.get("source_session_id"))
    source_session_file = _string(record.get("source_session_file"))
    handoff_file = _string(record.get("handoff_file"))
    created_at = _string(record.get("created_at"))
    if not all((project, source_session_id, source_session_file, handoff_file, created_at)):
        return None
    sequence = record.get("handoff_sequence")
    if not isinstance(sequence, int):
        sequence = 0
    marker = {
        "type": MARKER_TYPE,
        "created_at": created_at,
        "project": project,
        "source_session_id": source_session_id,
        "source_session_file": source_session_file,
        "handoff_file": handoff_file,
        "handoff_sequence": sequence,
    }
    replacement_session_id = _string(record.get("replacement_session_id"))
    replacement_session_file = _string(record.get("replacement_session_file"))
    if replacement_session_id:
        marker["replacement_session_id"] = replacement_session_id
    if replacement_session_file:
        marker["replacement_session_file"] = replacement_session_file
    return marker


def append_handoff_marker(
    marker_file: Path,
    *,
    project: str,
    source_session_id: str,
    source_session_file: str,
    handoff_file: str,
    replacement_session_id: str = "",
    replacement_session_file: str = "",
    created_at: str | None = None,
) -> dict[str, Any]:
    markers = load_handoff_markers(marker_file)
    sequence = (
        max(
            (marker["handoff_sequence"] for marker in markers if marker["project"] == project),
            default=0,
        )
        + 1
    )
    marker = {
        "type": MARKER_TYPE,
        "created_at": created_at or utc_now(),
        "project": project,
        "source_session_id": source_session_id,
        "source_session_file": source_session_file,
        "handoff_file": handoff_file,
        "handoff_sequence": sequence,
    }
    if replacement_session_id:
        marker["replacement_session_id"] = replacement_session_id
    if replacement_session_file:
        marker["replacement_session_file"] = replacement_session_file
    marker_file.parent.mkdir(parents=True, exist_ok=True)
    with marker_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(marker, separators=(",", ":")) + "\n")
    return marker


def session_identity(path: Path) -> dict[str, str]:
    project = ""
    session_id = ""
    thread_source = ""
    parent_thread_id = ""
    for _line_no, _raw, record in iter_jsonl(path):
        rtype = record.get("type")
        if rtype not in {"session_meta", "turn_context"}:
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if not project:
            value = payload.get("cwd") or payload.get("project") or payload.get("workdir")
            if isinstance(value, str):
                project = value
        if not session_id:
            value = payload.get("id") or payload.get("session_id")
            if isinstance(value, str):
                session_id = value
        if not thread_source:
            value = payload.get("thread_source")
            if isinstance(value, str):
                thread_source = value
            else:
                source = payload.get("source")
                if isinstance(source, dict) and isinstance(source.get("subagent"), dict):
                    thread_source = "subagent"
        if not parent_thread_id:
            value = payload.get("parent_thread_id")
            if isinstance(value, str):
                parent_thread_id = value
        if project and session_id and rtype == "session_meta":
            break
    return {
        "project": project or str(path.parent),
        "session_id": session_id,
        "thread_source": thread_source,
        "parent_thread_id": parent_thread_id,
    }


def is_user_owned_session(identity: dict[str, str]) -> bool:
    thread_source = identity.get("thread_source", "")
    if thread_source == "automation":
        return False
    return thread_source == "user" or not identity.get("parent_thread_id")


def marker_prompt_block(marker: dict[str, Any]) -> str:
    return "\n".join(
        [
            PROMPT_HEADER,
            f"source_session_id: {marker['source_session_id']}",
            f"handoff_file: {marker['handoff_file']}",
            f"project: {marker['project']}",
            f"handoff_sequence: {marker['handoff_sequence']}",
        ]
    )


def prompt_markers_for_session(path: Path) -> list[dict[str, Any]]:
    identity = session_identity(path)
    markers: list[dict[str, Any]] = []
    for _line_no, _raw, record in iter_jsonl(path):
        text = record_text(record)
        if PROMPT_HEADER not in text:
            continue
        parsed = parse_prompt_marker(text)
        if parsed is None:
            continue
        parsed["replacement_session_file"] = str(path)
        parsed["replacement_session_id"] = identity["session_id"]
        markers.append(parsed)
    return markers


def parse_prompt_marker(text: str) -> dict[str, Any] | None:
    lines = [line.strip() for line in text.splitlines()]
    try:
        start = lines.index(PROMPT_HEADER)
    except ValueError:
        return None
    fields: dict[str, str] = {}
    for line in lines[start + 1 : start + 8]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    source_session_id = fields.get("source_session_id", "")
    if not source_session_id:
        return None
    sequence_raw = fields.get("handoff_sequence", "0")
    try:
        sequence = int(sequence_raw)
    except ValueError:
        sequence = 0
    return {
        "source_session_id": source_session_id,
        "handoff_file": fields.get("handoff_file", ""),
        "project": fields.get("project", ""),
        "handoff_sequence": sequence,
    }


def record_text(record: dict[str, Any]) -> str:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return ""
    for key in ("message", "error", "text"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    content = payload.get("content")
    if isinstance(content, list):
        pieces: list[str] = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text")
                if isinstance(value, str):
                    pieces.append(value)
        return "\n".join(pieces)
    return ""


def retired_marker_for_result(
    result: dict[str, Any],
    markers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    result_path = path_key(result["file"])
    result_id = result.get("session_id", "")
    for marker in reversed(markers):
        if marker["source_session_id"] == result_id:
            return marker
        if path_key(marker["source_session_file"]) == result_path:
            return marker
    return None


def is_retired_session(path: Path, session_id: str, markers: list[dict[str, Any]]) -> bool:
    session_path = path_key(str(path))
    return any(
        marker["source_session_id"] == session_id
        or path_key(marker["source_session_file"]) == session_path
        for marker in markers
    )


def handoff_summary_for_project(
    project: str,
    markers: list[dict[str, Any]],
) -> dict[str, Any]:
    project_markers = [marker for marker in markers if marker["project"] == project]
    latest = max(project_markers, key=lambda marker: marker["created_at"], default=None)
    return {
        "total_handoffs": len(project_markers),
        "latest_handoff_at": latest["created_at"] if latest else "",
        "latest_handoff_file": latest["handoff_file"] if latest else "",
        "retired_source_sessions": len(
            {marker["source_session_id"] for marker in project_markers}
        ),
    }


def replacement_prompt_markers(session_paths: list[Path]) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for path in session_paths:
        try:
            markers.extend(prompt_markers_for_session(path))
        except OSError:
            continue
    return markers


def marker_aware_active_sessions_by_project(
    session_root: Path,
    markers: list[dict[str, Any]],
) -> list[Path]:
    grouped: dict[str, list[tuple[float, Path, str, bool, bool]]] = {}
    for path in session_root.rglob("*.jsonl"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            identity = session_identity(path)
        except OSError:
            continue
        retired = is_retired_session(path, identity["session_id"], markers)
        grouped.setdefault(identity["project"], []).append(
            (
                stat.st_mtime,
                path,
                identity["session_id"],
                retired,
                is_user_owned_session(identity),
            )
        )

    selected: list[Path] = []
    for sessions in grouped.values():
        active = [session for session in sessions if not session[3]]
        candidates = active or sessions
        user_owned = [session for session in candidates if session[4]]
        candidates = user_owned or candidates
        selected.append(max(candidates, key=lambda item: item[0])[1])
    return sorted(selected, key=str)


def annotate_result_with_handoff_context(
    result: dict[str, Any],
    markers: list[dict[str, Any]],
    replacement_markers: list[dict[str, Any]],
) -> dict[str, Any]:
    retired = retired_marker_for_result(result, markers)
    replaces = [
        marker["source_session_id"]
        for marker in replacement_markers
        if marker.get("replacement_session_file") == result["file"]
    ]
    result_path = path_key(result["file"])
    result_id = result.get("session_id", "")
    replaces.extend(
        marker["source_session_id"]
        for marker in markers
        if marker.get("replacement_session_id") == result_id
        or (
            marker.get("replacement_session_file")
            and path_key(marker["replacement_session_file"]) == result_path
        )
    )
    result["handoff_summary"] = handoff_summary_for_project(result["project"], markers)
    result["retired_by_handoff"] = retired
    result["replaces_session_ids"] = sorted(set(replaces))
    result["session_role"] = "retired" if retired else "active"
    if retired:
        result["underlying_status"] = result["status"]
        result["underlying_recommendation"] = result["recommendation"]
        result["underlying_reasons"] = result["reasons"]
        result["status"] = "retired"
        result["continuation_status"] = "retired"
        result["recommendation"] = "use-replacement-thread"
        result["reasons"] = ["session was retired by completed handoff"]
        result["handoff_readiness"] = {
            "status": "completed",
            "recommendation": "use-replacement-thread",
            "visual_archive": "not-needed",
            "reasons": ["session was retired by completed handoff"],
        }
    return result


def path_key(value: str) -> str:
    return str(Path(value).expanduser().resolve())


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""
