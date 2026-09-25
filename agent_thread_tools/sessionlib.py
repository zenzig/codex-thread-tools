"""Session JSONL primitives shared by agent-thread-tools tools."""

from __future__ import annotations

import hashlib
import json
import os
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


def open_claude_sessions(registry: Path | None = None) -> set[str]:
    """Session ids of Claude Code sessions whose process is still running."""
    from agent_thread_tools.sessionpaths import claude_session_registry

    registry = registry or claude_session_registry()
    if not registry.is_dir():
        return set()
    open_ids: set[str] = set()
    for entry in registry.glob("*.json"):
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("sessionId"), str):
            continue
        if _process_alive(data.get("pid"), data.get("procStart")):
            open_ids.add(data["sessionId"])
    return open_ids


def _process_alive(pid: Any, proc_start: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    stat = Path(f"/proc/{pid}/stat")
    if stat.parent.parent.is_dir() and Path("/proc/self").exists():
        try:
            fields = stat.read_text().rsplit(")", 1)[1].split()
        except OSError:
            return False
        # A reused pid has a different start time than the one Claude Code recorded.
        return not isinstance(proc_start, str) or fields[19] == proc_start
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def session_agent(path: Path) -> str:
    """``claude`` or ``codex``, from the first record in a session file."""
    from agent_thread_tools.claude_sessions import is_claude_record

    with path.open("rb") as handle:
        for raw in handle:
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                return "claude" if is_claude_record(record) else "codex"
    return "codex"


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


def iter_session_records(path: Path) -> Iterable[tuple[int, bytes, dict[str, Any]]]:
    """Yield session records in Codex shape, translating Claude Code sessions.

    Codex records pass through unchanged. A Claude Code line can become several
    Codex records; only the first carries the raw line so byte totals stay exact.
    """
    from agent_thread_tools.claude_sessions import ClaudeTranslator, is_claude_record

    translator: ClaudeTranslator | None = None
    for line_no, raw, record in iter_jsonl(path):
        if translator is None and not is_claude_record(record):
            yield line_no, raw, record
            continue
        translator = translator or ClaudeTranslator()
        for index, translated in enumerate(translator.translate(record)):
            yield line_no, raw if index == 0 else b"", translated


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
