"""Shared helpers for agent-thread-tools tools."""

from pathlib import Path


def _read_version() -> str:
    try:
        return (Path(__file__).resolve().parents[1] / "VERSION").read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        return "0.0.0"


__version__ = _read_version()

from agent_thread_tools.sessionlib import (
    KEEP_EVENT_TYPES,
    die,
    expand_path,
    is_codex_running,
    iter_jsonl,
    iter_session_records,
    now_iso,
    now_stamp,
    payload_role,
    payload_type,
    record_timestamp,
)
from agent_thread_tools.thread_health import HealthThresholds, analyze_session_file
from agent_thread_tools.visual_artifacts import archive_visuals, scan_session_visuals, verify_manifest

__all__ = [
    "HealthThresholds",
    "KEEP_EVENT_TYPES",
    "__version__",
    "analyze_session_file",
    "archive_visuals",
    "die",
    "expand_path",
    "is_codex_running",
    "iter_jsonl",
    "iter_session_records",
    "now_iso",
    "now_stamp",
    "payload_role",
    "payload_type",
    "record_timestamp",
    "scan_session_visuals",
    "verify_manifest",
]
