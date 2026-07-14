"""Utility helpers for redacting sensitive text from session payloads."""

from __future__ import annotations

import re
from typing import Callable, Union


Replacement = Union[str, Callable[[re.Match[str]], str]]


_SUFFIX_RE = re.compile(r"(?P<value>.*?)(?P<suffix>[\]}`>\.]+)?$")
_SECRET_LABEL_KEYWORDS = (
    "api",
    "access",
    "token",
    "secret",
    "password",
    "credential",
    "auth",
    "key",
)


def _replace_auth_header(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}[REDACTED]"


def _replace_uri_userinfo(match: re.Match[str]) -> str:
    return f"{match.group('scheme')}[REDACTED]@{match.group('rest')}"


def _is_already_redacted(value: str) -> bool:
    return value == "[REDACTED]" or re.fullmatch(r"\[REDACTED\][^\w\s]*", value) is not None


def _split_value_and_suffix(value: str) -> tuple[str, str]:
    match = _SUFFIX_RE.match(value)
    if not match:
        return value, ""
    return match.group("value"), match.group("suffix") or ""


def _normalize_label(label: str) -> str:
    if label and label[0] in {'"', "'"} and label[-1] == label[0]:
        return label[1:-1]
    return label


def _is_secret_label(label: str) -> bool:
    raw_label = _normalize_label(label)
    normalized = raw_label.lower()
    if not normalized:
        return False
    if re.search(
        r"(?<![a-z0-9])(?:api[_-]?key|access[_-]?token|client[_-]?secret|secret|password|passwd|credential|key)(?![a-z0-9])",
        normalized,
    ):
        return True
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", raw_label) and normalized.endswith(
        ("key", "token", "secret", "password", "passwd", "credential", "auth")
    ):
        return True

    parts = [
        part
        for part in re.split(
            r"(?<=[a-z0-9])(?=[A-Z])|[^a-zA-Z0-9]+", raw_label
        )
        if part
    ]
    if len(parts) > 1:
        lowered_parts = [part.lower() for part in parts]
        if lowered_parts[-1] == "token":
            return True
        return lowered_parts[-1] in _SECRET_LABEL_KEYWORDS

    normalized_part = parts[0].lower() if parts else normalized
    return any(
        normalized_part == keyword
        or normalized_part.startswith(f"{keyword}_")
        or normalized_part.endswith(f"_{keyword}")
        or (normalized_part == "key")
        or (keyword != "key" and normalized_part.endswith(keyword))
        for keyword in _SECRET_LABEL_KEYWORDS
    )


def _replace_labeled_assignment(match: re.Match[str]) -> str:
    export = match.group("export") or ""
    label = match.group("label")
    sep = match.group("sep")
    ws = match.group("ws")
    value = match.group("value")
    if not _is_secret_label(label):
        return match.group(0)

    if _is_already_redacted(value):
        return match.group(0)

    value = value.rstrip()
    suffix_value, suffix = _split_value_and_suffix(value)
    if suffix_value == "":
        return f"{match.group('prefix')}{export}{label}{sep}{ws}[REDACTED]"
    if suffix_value[0] in {"'", '"'} and suffix_value[-1] == suffix_value[0]:
        value_core = suffix_value[1:-1]
        if _is_already_redacted(value_core):
            return match.group(0)
        quote = suffix_value[0]
        return (
            f"{match.group('prefix')}{export}{label}{sep}{ws}{quote}"
            f"[REDACTED]{quote}{suffix}"
        )

    if _is_already_redacted(suffix_value):
        return match.group(0)
    return (
        f"{match.group('prefix')}{export}{label}{sep}{ws}[REDACTED]{suffix}"
    )


def _replace_query_assignment(match: re.Match[str]) -> str:
    label = match.group("label")
    if not _is_secret_label(label):
        return match.group(0)

    value = match.group("value")
    if _is_already_redacted(value):
        return match.group(0)

    suffix_value, suffix = _split_value_and_suffix(value)
    if _is_already_redacted(suffix_value):
        return match.group(0)

    if suffix_value == "":
        return f"{match.group('prefix')}{label}=[REDACTED]"
    return f"{match.group('prefix')}{label}=[REDACTED]{suffix}"


_PEM_MARKER_RE = re.compile(
    r"(?m)-----\s*(?P<kind>BEGIN|END) "
    r"(?P<pem_type>(?:[A-Z0-9-]+ )*PRIVATE KEY)-----",
    re.IGNORECASE,
)


def _redact_pem_blocks(value: str) -> tuple[str, int]:
    starts: list[int] = []
    spans: list[tuple[int, int]] = []
    for marker in _PEM_MARKER_RE.finditer(value):
        kind = marker.group("kind").upper()
        if kind == "BEGIN":
            starts.append(marker.start())
        elif starts:
            spans.append((starts.pop(), marker.end()))

    if not spans and not starts:
        return value, 0
    for start in starts:
        spans.append((start, len(value)))

    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    parts: list[str] = []
    cursor = 0
    for start, end in merged:
        parts.extend((value[cursor:start], "[REDACTED]"))
        cursor = end
    parts.append(value[cursor:])
    return "".join(parts), len(merged)


SENSITIVE_RULES: tuple[tuple[re.Pattern[str], Replacement], ...] = (
    (
        re.compile(
            r"(?im)(?P<prefix>Authorization:\s*(?:Basic|Bearer)\s+)[^\s]+"
        ),
        _replace_auth_header,
    ),
    (
        re.compile(
            r"(?i)\b(?P<scheme>[a-z][a-z0-9+.-]*://)"
            r"(?P<user>[^/\s:@?#]+):(?P<password>[^/\s@?#]+)@"
            r"(?P<rest>[^/\s@?#]+(?:[/?#][^\s]*)?)(?=\s|$)"
        ),
        _replace_uri_userinfo,
    ),
    (
        re.compile(
            r"(?im)(?P<prefix>^|[\s{,])(?P<export>export\s+)?"
            r"(?P<label>[A-Za-z_][A-Za-z0-9_-]*|\"[^\"]+\"|'[^']+')\s*"
            r"(?P<sep>[:=])(?P<ws>\s*)(?P<value>'(?:\\\\.|[^'\\\\])*'|\"(?:\\\\.|[^\"\\\\])*\"|[^\s#]+)"
        ),
        _replace_labeled_assignment,
    ),
    (
        re.compile(
            r"(?P<prefix>[?&])(?P<label>[A-Za-z0-9_-]+)(?P<sep>=)(?P<value>[^\s#&]+)"
        ),
        _replace_query_assignment,
    ),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"), "[REDACTED]"),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "[REDACTED]"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"), "[REDACTED]"),
    (re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9_-]{20,}\b"), "[REDACTED]"),
    (
        re.compile(
            r"\bxox[A-Za-z]+-[A-Za-z0-9]+-[A-Za-z0-9]+"
            r"(?:-[A-Za-z0-9]+)*\b"
        ),
        "[REDACTED]",
    ),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"), "[REDACTED]"),
    (re.compile(r"\bnpm_[A-Za-z0-9_-]{20,}\b"), "[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"), "[REDACTED]"),
    (
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{1,}\.[A-Za-z0-9_-]{1,}\.[A-Za-z0-9_-]{1,}\b"
        ),
        "[REDACTED]",
    ),
)


def redact_sensitive_text(value: str) -> tuple[str, int]:
    """Return redacted text and the number of replacements made."""
    redacted, count = _redact_pem_blocks(value)
    for pattern, replacement in SENSITIVE_RULES:
        if isinstance(replacement, str):
            redacted, replacements = pattern.subn(replacement, redacted)
            count += replacements
            continue

        changed = 0

        def _replace(match: re.Match[str]) -> str:
            nonlocal changed
            replacement_text = replacement(match)
            if replacement_text != match.group(0):
                changed += 1
            return replacement_text

        redacted = pattern.sub(_replace, redacted)
        count += changed

    return redacted, count
