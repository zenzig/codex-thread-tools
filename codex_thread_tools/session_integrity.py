"""Structural scanner for session-integrity image signals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codex_thread_tools.sessionlib import iter_jsonl

INPUT_IMAGE_TYPES = frozenset({"input_image", "InputImage", "inputImage"})
INPUT_IMAGE_URL_KEY_BY_TYPE = {
    "inputImage": "imageUrl",
}
CANONICAL_INPUT_IMAGE_KIND = "input_image"
TOOL_OUTPUT_IMAGE_KIND = "tool_output_image"
REPLAYABLE_TOOL_OUTPUT_TYPES = frozenset(
    {"custom_tool_call_output", "function_call_output"}
)
INLINE_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>image/[A-Za-z0-9.+-]+);base64,(?P<data>[A-Za-z0-9+/=]+)$"
)
INVALID_INLINE_IMAGE_CODE = "invalid_data_url"
REMOTE_IMAGE_CODE = "remote_http_image_url"
ALLOWED_BASE64_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
DEFAULT_MAX_FINDINGS = 50


@dataclass(frozen=True)
class SessionIntegrityFinding:
    kind: str
    line: int
    compacted: bool
    code: str


@dataclass(frozen=True)
class SessionIntegrityScanResult:
    invalid_image_urls: int
    invalid_image_urls_in_compacted_records: int
    remote_image_urls: int
    remote_image_urls_in_compacted_records: int
    history_base_present: bool
    findings: tuple[SessionIntegrityFinding, ...]


class SessionIntegrityAccumulator:
    """Incrementally collect structural session-integrity signals."""

    def __init__(self, *, max_findings: int = DEFAULT_MAX_FINDINGS) -> None:
        if type(max_findings) is not int or max_findings < 0:
            raise ValueError("max_findings must be a non-negative integer")

        self._max_findings = max_findings
        self._state: dict[str, int | bool] = {
            "invalid_image_urls": 0,
            "invalid_image_urls_in_compacted_records": 0,
            "remote_image_urls": 0,
            "remote_image_urls_in_compacted_records": 0,
            "history_base_present": False,
        }
        self._findings: list[SessionIntegrityFinding] = []

    def scan_record(self, record: dict[str, Any], *, line_no: int) -> None:
        if "history_base" in record:
            self._state["history_base_present"] = True

        _scan_live_record(
            record,
            line_no=line_no,
            compacted=False,
            state=self._state,
            findings=self._findings,
            max_findings=self._max_findings,
        )

        if record.get("type") != "compacted":
            return
        payload = record.get("payload")
        if isinstance(payload, dict):
            _scan_replacement_history(
                payload.get("replacement_history"),
                line_no=line_no,
                state=self._state,
                findings=self._findings,
                max_findings=self._max_findings,
            )

    def result(self) -> SessionIntegrityScanResult:
        return SessionIntegrityScanResult(
            findings=tuple(self._findings),
            **self._state,
        )


def scan_session_integrity(
    path: Path,
    *,
    max_findings: int = DEFAULT_MAX_FINDINGS,
) -> SessionIntegrityScanResult:
    accumulator = SessionIntegrityAccumulator(max_findings=max_findings)

    for line_no, _raw, record in iter_jsonl(path):
        accumulator.scan_record(record, line_no=line_no)

    return accumulator.result()


def _scan_live_record(
    record: dict[str, Any],
    *,
    line_no: int,
    compacted: bool,
    state: dict[str, int | bool],
    findings: list[SessionIntegrityFinding],
    max_findings: int,
) -> None:
    if record.get("type") != "response_item":
        return

    payload = record.get("payload")
    if not isinstance(payload, dict):
        return

    _scan_replayable_payload(
        payload,
        line_no=line_no,
        compacted=compacted,
        state=state,
        findings=findings,
        max_findings=max_findings,
    )


def _scan_replayable_payload(
    payload: dict[str, Any],
    *,
    line_no: int,
    compacted: bool,
    state: dict[str, int | bool],
    findings: list[SessionIntegrityFinding],
    max_findings: int,
) -> None:
    if _is_canonical_message_payload(payload):
        items = payload["content"]
        finding_kind = CANONICAL_INPUT_IMAGE_KIND
    elif _is_replayable_tool_output_payload(payload):
        items = payload["output"]
        finding_kind = TOOL_OUTPUT_IMAGE_KIND
    else:
        return

    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if not isinstance(kind, str) or kind not in INPUT_IMAGE_TYPES:
            continue
        image_url = _extract_image_url(item)
        if not isinstance(image_url, str):
            continue

        if _is_http_image_url(image_url):
            state["remote_image_urls"] += 1
            if compacted:
                state["remote_image_urls_in_compacted_records"] += 1
            _append_finding(
                findings,
                finding_kind,
                line_no,
                compacted,
                REMOTE_IMAGE_CODE,
                max_findings,
            )
        elif _is_valid_data_image_url(image_url):
            continue
        else:
            state["invalid_image_urls"] += 1
            if compacted:
                state["invalid_image_urls_in_compacted_records"] += 1
            _append_finding(
                findings,
                finding_kind,
                line_no,
                compacted,
                INVALID_INLINE_IMAGE_CODE,
                max_findings,
            )


def _scan_replacement_history(
    replacement_history: Any,
    *,
    line_no: int,
    state: dict[str, int | bool],
    findings: list[SessionIntegrityFinding],
    max_findings: int,
) -> None:
    if not isinstance(replacement_history, list):
        return

    for nested in replacement_history:
        if not isinstance(nested, dict):
            continue
        _scan_replayable_payload(
            nested,
            line_no=line_no,
            compacted=True,
            state=state,
            findings=findings,
            max_findings=max_findings,
        )


def _is_canonical_message_payload(payload: dict[str, Any]) -> bool:
    return payload.get("type") == "message" and isinstance(payload.get("content"), list)


def _is_replayable_tool_output_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("type") in REPLAYABLE_TOOL_OUTPUT_TYPES
        and isinstance(payload.get("output"), list)
    )


def _extract_image_url(item: dict[str, Any]) -> Any:
    item_type = item.get("type")
    if not isinstance(item_type, str):
        return None
    key = INPUT_IMAGE_URL_KEY_BY_TYPE.get(item_type, "image_url")
    return item.get(key)


def _is_valid_data_image_url(value: str) -> bool:
    match = INLINE_DATA_URL_RE.fullmatch(value)
    if not match:
        return False
    data = match.group("data")
    if not data:
        return False
    if any(character not in ALLOWED_BASE64_CHARS for character in data):
        return False
    if not _has_valid_base64_padding(data):
        return False
    return True


def _has_valid_base64_padding(data: str) -> bool:
    if not data:
        return False

    if "=" not in data:
        return len(data) % 4 in {0, 2, 3}

    trailing_padding = len(data) - len(data.rstrip("="))
    if trailing_padding not in {1, 2}:
        return False

    prefix = data[: -trailing_padding]
    if not prefix or "=" in prefix:
        return False
    return len(data) % 4 == 0


def _is_http_image_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _append_finding(
    findings: list[SessionIntegrityFinding],
    kind: str,
    line_no: int,
    compacted: bool,
    code: str,
    max_findings: int,
) -> None:
    if len(findings) >= max_findings:
        return
    findings.append(
        SessionIntegrityFinding(
            kind=kind,
            line=line_no,
            compacted=compacted,
            code=code,
        )
    )
