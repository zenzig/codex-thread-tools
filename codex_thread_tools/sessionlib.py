"""Session JSONL primitives shared by codex-thread-tools tools."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CODEX_PROCESS_NAME_PATTERN = re.compile(
    r'(^|[\\/"\s,])Codex(?: Helper)?(?:\.exe)?($|[\\/"\s,])'
)
PROCESS_LIST_TIMEOUT_SECONDS = 2
KEEP_EVENT_TYPES = {"user_message", "agent_message", "task_complete"}


def die(message: str) -> None:
    raise SystemExit(f"error: {message}")


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def expand_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def process_listing_command(system: str | None = None) -> list[str]:
    current = system or platform.system()
    if current == "Windows":
        return ["tasklist", "/FO", "CSV", "/NH"]
    if current == "Darwin":
        return ["ps", "-axo", "comm,args"]
    return ["ps", "-eo", "comm,args"]


def process_line_looks_like_codex(line: str) -> bool:
    return bool(CODEX_PROCESS_NAME_PATTERN.search(line))


def is_codex_running() -> bool:
    try:
        result = subprocess.run(
            process_listing_command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=PROCESS_LIST_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    return any(
        process_line_looks_like_codex(line)
        for line in result.stdout.splitlines()
    )


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
