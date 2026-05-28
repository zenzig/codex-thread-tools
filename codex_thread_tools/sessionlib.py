"""Session JSONL primitives shared by codex-thread-tools tools."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CODEX_PROCESS_PATTERN = r"/Applications/Codex.app|Codex Helper|Codex.app/Contents"
KEEP_EVENT_TYPES = {"user_message", "agent_message", "task_complete"}


def die(message: str) -> None:
    raise SystemExit(f"error: {message}")


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def expand_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def is_codex_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", CODEX_PROCESS_PATTERN],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def iter_jsonl(path: Path) -> Iterable[tuple[int, bytes, dict[str, Any]]]:
    with path.open("rb") as handle:
        for line_no, raw in enumerate(handle, 1):
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                die(f"{path} has invalid JSON at line {line_no}: {exc}")
            if not isinstance(record, dict):
                die(f"{path} line {line_no} is not a JSON object")
            yield line_no, raw, record


def payload_type(record: dict[str, Any]) -> str:
    payload = record.get("payload")
    if isinstance(payload, dict):
        value = payload.get("type")
        if isinstance(value, str):
            return value
    return ""


def payload_role(record: dict[str, Any]) -> str:
    payload = record.get("payload")
    if isinstance(payload, dict):
        value = payload.get("role")
        if isinstance(value, str):
            return value
    return ""


def record_timestamp(record: dict[str, Any]) -> str:
    value = record.get("timestamp")
    return value if isinstance(value, str) else ""
