"""Build redacted handoff summary drafts from Codex session JSONL files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from codex_thread_tools.display import format_count
from codex_thread_tools.sessionlib import iter_jsonl, payload_role, payload_type, record_timestamp
from codex_thread_tools.thread_health import (
    HealthThresholds,
    analyze_session_file,
    record_text,
)


TOOL_PAYLOAD_TYPES = {
    "custom_tool_call",
    "custom_tool_call_output",
    "function_call",
    "function_call_output",
    "image_generation_call",
    "local_shell_call",
    "mcp_tool_call",
    "mcp_tool_call_output",
    "tool_call",
    "tool_result",
    "web_search_call",
}

SENSITIVE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]+\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]+\b"),
    re.compile(
        r"(?i)\b(api[_ -]?key|secret|token|password)\s*[:=]\s*['\"]?[^'\"\s]+"
    ),
)


def build_handoff_summary(
    session_file: Path,
    *,
    thresholds: HealthThresholds | None = None,
    max_items: int = 8,
    max_text_chars: int = 500,
) -> dict[str, Any]:
    health = analyze_session_file(session_file, thresholds or HealthThresholds())
    redactions = {
        "tool_payloads_omitted": 0,
        "bulky_payloads_omitted": 0,
        "sensitive_values_redacted": 0,
        "truncated_items": 0,
    }
    durable_context = durable_context_items(
        session_file,
        max_items=max_items,
        max_text_chars=max_text_chars,
        redactions=redactions,
    )
    metrics = health["metrics"]
    return {
        "summary_type": "handoff_summary",
        "file": health["file"],
        "project": health["project"],
        "session_id": health["session_id"],
        "health": {
            "status": health["status"],
            "recommendation": health["recommendation"],
            "handoff_readiness": health["handoff_readiness"],
            "reasons": health["reasons"],
        },
        "pre_handoff_safety": pre_handoff_safety(metrics, health),
        "compaction": {
            "request_items": metrics["compaction_request_items"],
            "installed_checkpoints": metrics["installed_compaction_checkpoints"],
            "latest_state": metrics["latest_compaction_state"],
            "latest_installed": metrics["latest_compaction_installed"],
        },
        "visuals": {
            "references": metrics["visual_artifacts"],
            "in_compacted_records": metrics["visual_artifacts_in_compacted_records"],
            "archive_recommended": health["handoff_readiness"]["visual_archive"],
        },
        "durable_context": durable_context,
        "redactions": redactions,
    }


def durable_context_items(
    session_file: Path,
    *,
    max_items: int,
    max_text_chars: int,
    redactions: dict[str, int],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for _line_no, _raw, record in iter_jsonl(session_file):
        rtype = record.get("type")
        ptype = payload_type(record)
        if rtype == "response_item" and is_tool_payload_type(ptype):
            redactions["tool_payloads_omitted"] += 1
            continue
        if rtype == "compacted":
            redactions["bulky_payloads_omitted"] += 1
            continue
        if not is_context_record(record):
            continue
        text = normalize_text(record_text(record))
        if not text:
            continue
        text, sensitive_count = redact_sensitive_text(text)
        redactions["sensitive_values_redacted"] += sensitive_count
        if len(text) > max_text_chars:
            text = text[: max_text_chars - 3].rstrip() + "..."
            redactions["truncated_items"] += 1
        items.append(
            {
                "timestamp": record_timestamp(record),
                "role": context_role(record),
                "text": text,
            }
        )
    if max_items <= 0:
        return []
    return items[-max_items:]


def is_tool_payload_type(value: str) -> bool:
    if value in TOOL_PAYLOAD_TYPES:
        return True
    lowered = value.lower()
    return "tool" in lowered or "function_call" in lowered


def is_context_record(record: dict[str, Any]) -> bool:
    rtype = record.get("type")
    ptype = payload_type(record)
    if rtype == "response_item" and ptype == "message":
        return True
    return rtype == "event_msg" and ptype in {"user_message", "agent_message"}


def context_role(record: dict[str, Any]) -> str:
    role = payload_role(record)
    if role:
        return role
    ptype = payload_type(record)
    if ptype == "user_message":
        return "user"
    if ptype == "agent_message":
        return "assistant"
    return "unknown"


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def redact_sensitive_text(value: str) -> tuple[str, int]:
    redacted = value
    count = 0
    for pattern in SENSITIVE_PATTERNS:
        redacted, replacements = pattern.subn("[REDACTED]", redacted)
        count += replacements
    return redacted, count


def pre_handoff_safety(metrics: dict[str, Any], health: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    if metrics["unresolved_turn_error_events"] > 0:
        reasons.append("unresolved turn abort or error event was recorded")
    if metrics["incomplete_turn_events"] > 0:
        reasons.append("active turn has no terminal completion, abort, or error event")
    if metrics["compaction_failures"]:
        reasons.append("compaction failure or context-window error event was recorded")
    if metrics["recovered_turn_error_events"] > 0:
        reasons.append("historical turn abort or error event was recovered by later completion")

    if metrics["unresolved_turn_error_events"] > 0 or metrics["compaction_failures"]:
        status = "blocked"
    elif reasons or health["status"] == "warn":
        status = "caution"
    else:
        status = "clean"

    return {
        "status": status,
        "reasons": reasons,
        "incomplete_turn_events": metrics["incomplete_turn_events"],
        "unresolved_turn_error_events": metrics["unresolved_turn_error_events"],
        "recovered_turn_error_events": metrics["recovered_turn_error_events"],
        "latest_turn_event": metrics["latest_turn_event"],
    }


def format_handoff_summary(summary: dict[str, Any]) -> str:
    safety = summary["pre_handoff_safety"]
    health = summary["health"]
    compaction = summary["compaction"]
    visuals = summary["visuals"]
    redactions = summary["redactions"]
    lines = [
        "Codex Thread Handoff Summary",
        f"Project: {summary['project']}",
        f"Session: {summary['session_id'] or 'not recorded'}",
        f"File: {summary['file']}",
        f"Health: {health['status'].upper()} ({health['recommendation']})",
        f"Pre-handoff safety: {safety['status'].upper()}",
    ]
    for reason in safety["reasons"]:
        lines.append(f"  - {reason}")
    lines.extend(
        [
            "",
            "Compaction",
            f"Request items: {format_count(compaction['request_items'])}",
            f"Installed checkpoints: {format_count(compaction['installed_checkpoints'])}",
            f"Latest state: {compaction['latest_state']}",
            "",
            "Visuals",
            f"References: {format_count(visuals['references'])}",
            f"Inside compacted records: {format_count(visuals['in_compacted_records'])}",
            f"Archive recommended: {visuals['archive_recommended']}",
            "",
            "Durable Context",
        ]
    )
    if summary["durable_context"]:
        for item in summary["durable_context"]:
            lines.append(f"- {item['role']}: {item['text']}")
    else:
        lines.append("- No durable message context found.")
    lines.extend(
        [
            "",
            "Redactions",
            f"Tool payloads omitted: {format_count(redactions['tool_payloads_omitted'])}",
            f"Bulky payloads omitted: {format_count(redactions['bulky_payloads_omitted'])}",
            f"Sensitive values redacted: {format_count(redactions['sensitive_values_redacted'])}",
            f"Truncated items: {format_count(redactions['truncated_items'])}",
        ]
    )
    return "\n".join(lines)
