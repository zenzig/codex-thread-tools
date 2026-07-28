"""Read-only health analysis for Codex session JSONL files."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codex_thread_tools.sessionlib import (
    iter_jsonl,
    payload_role,
    payload_type,
    record_text,
    record_timestamp,
)
from codex_thread_tools.sessionpaths import default_session_root
from codex_thread_tools.session_integrity import SessionIntegrityAccumulator
from codex_thread_tools.visual_artifacts import scan_record_visual_metrics


DEFAULT_WARN_BYTES = 500 * 1024 * 1024
DEFAULT_DANGER_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_WARN_ITEMS = 8_000
DEFAULT_DANGER_ITEMS = 12_000
DEFAULT_MAX_HEALTHY_COMPACTIONS = 3

COMPACTION_FAILURE_DIAGNOSTIC = (
    "compaction failure or context-window error event was recorded"
)
LONG_THREAD_DIAGNOSTIC = "long-thread or context-window warning event was recorded"

ACTIVE_TURN_DIAGNOSTIC = "active turn has no terminal completion, abort, or error event"
COMPACTED_VISUAL_REFERENCE_DIAGNOSTIC = (
    "visual references exist inside compacted replacement history"
)
RECOVERED_CONTINUITY_WARNING_DIAGNOSTIC = (
    "historical turn abort or error event was recovered by later completion"
)
INSTALLED_COMPACTION_PRESSURE_DIAGNOSTIC = (
    "installed compaction checkpoints exceed healthy threshold"
)

TASK_STATES = ("active", "completed", "interrupted", "unknown")
CONTINUATION_RISK_STATES = ("ok", "watch", "danger")
SCALE_LEVELS = ("ok", "notice", "watch", "danger")
HANDOFF_LINEAGE_STATES = (
    "not-recorded",
    "replacement-active",
    "source-retired",
    "incomplete",
)
ACTION_STATES = (
    "continue",
    "finish-current-turn",
    "prepare-handoff",
    "handoff-now",
    "use-replacement",
)

STATUS_RANK = {"ok": 0, "warn": 1, "danger": 2}
SCALE_RANK = {"ok": 0, "notice": 1, "watch": 2, "danger": 3}
NOTICE_DIAGNOSTICS = {
    ACTIVE_TURN_DIAGNOSTIC,
    COMPACTED_VISUAL_REFERENCE_DIAGNOSTIC,
    RECOVERED_CONTINUITY_WARNING_DIAGNOSTIC,
}

COMPACTION_FAILURE_TERMS = (
    "compaction failed",
    "remote compaction failed",
    "remote compaction v2",
    "compact endpoint",
    "maximum length",
    "context window",
)
LONG_THREAD_TERMS = (
    "long threads and multiple compactions",
    "start a new thread",
)
EVENT_TYPE_ALIASES = {
    "task_started": "turn_started",
    "task_complete": "turn_complete",
}


@dataclass(frozen=True)
class HealthThresholds:
    warn_bytes: int = DEFAULT_WARN_BYTES
    danger_bytes: int = DEFAULT_DANGER_BYTES
    warn_items: int = DEFAULT_WARN_ITEMS
    danger_items: int = DEFAULT_DANGER_ITEMS
    max_healthy_compactions: int = DEFAULT_MAX_HEALTHY_COMPACTIONS


def thresholds_from_env() -> HealthThresholds:
    return HealthThresholds(
        warn_bytes=_env_int("CODEX_SIZE_WARN_BYTES", DEFAULT_WARN_BYTES),
        danger_bytes=_env_int("CODEX_SIZE_DANGER_BYTES", DEFAULT_DANGER_BYTES),
        warn_items=_env_int("CODEX_SIZE_WARN_ITEMS", DEFAULT_WARN_ITEMS),
        danger_items=_env_int("CODEX_SIZE_DANGER_ITEMS", DEFAULT_DANGER_ITEMS),
        max_healthy_compactions=_env_int(
            "CODEX_MAX_HEALTHY_COMPACTIONS", DEFAULT_MAX_HEALTHY_COMPACTIONS
        ),
    )


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"error: {name} must be an integer") from exc


def analyze_session_file(path: Path, thresholds: HealthThresholds) -> dict[str, Any]:
    stat = path.stat()
    metrics: dict[str, Any] = {
        "bytes": stat.st_size,
        "max_line_bytes": 0,
        "total_records": 0,
        "session_meta_records": 0,
        "turn_context_records": 0,
        "response_items": 0,
        "response_messages": 0,
        "event_messages": 0,
        "compacted_records": 0,
        "compacted_bytes": 0,
        "compacted_payload_percent": 0.0,
        "latest_compacted_timestamp": "",
        "latest_compaction_has_replacement_history": False,
        "latest_compaction_installed": False,
        "latest_compaction_state": "none",
        "legacy_compacted_records": 0,
        "installed_compaction_checkpoints": 0,
        "max_replacement_history_items": 0,
        "max_replacement_history_bytes": 0,
        "compaction_request_items": 0,
        "compaction_items": 0,
        "context_compaction_items": 0,
        "compaction_triggers": 0,
        "compaction_failures": [],
        "long_thread_warnings": [],
        "context_compacted_events": 0,
        "turn_started_events": 0,
        "turn_complete_events": 0,
        "turn_aborted_events": 0,
        "turn_terminal_events": 0,
        "incomplete_turn_events": 0,
        "latest_turn_event": "",
        "error_events": 0,
        "recovered_turn_error_events": 0,
        "unresolved_turn_error_events": 0,
        "token_count_events": 0,
        "first_token_timestamp": "",
        "latest_token_timestamp": "",
        "latest_token_total": None,
        "latest_active_token_total": None,
        "latest_token_usage": None,
        "latest_active_token_usage": None,
        "latest_model_context_window": None,
        "latest_token_ratio": None,
        "latest_cumulative_token_ratio": None,
        "visual_artifacts": 0,
        "visual_embedded_artifacts": 0,
        "visual_local_references": 0,
        "visual_video_artifacts": 0,
        "visual_embedded_bytes": 0,
        "largest_visual_artifact_bytes": 0,
        "visual_artifact_errors": 0,
        "visual_artifact_skipped": 0,
        "visual_artifacts_in_compacted_records": 0,
        "invalid_image_urls": 0,
        "invalid_image_urls_in_compacted_records": 0,
        "remote_image_urls": 0,
        "session_integrity_findings": 0,
        "history_base_present": False,
        "first_timestamp": "",
        "last_timestamp": "",
        "mtime_iso": _iso_from_timestamp(stat.st_mtime),
        "age_minutes": _age_minutes(stat.st_mtime),
    }
    project = ""
    session_id = ""
    turn_error_events_since_last_success = 0
    open_turn_events = 0
    integrity_accumulator = SessionIntegrityAccumulator(max_findings=0)

    for line_no, raw, record in iter_jsonl(path):
        integrity_accumulator.scan_record(record, line_no=line_no)
        metrics["total_records"] += 1
        metrics["max_line_bytes"] = max(metrics["max_line_bytes"], len(raw))
        rtype = record.get("type")
        ptype = payload_type(record)
        ts = record_timestamp(record)

        if ts and not metrics["first_timestamp"]:
            metrics["first_timestamp"] = ts
        if ts:
            metrics["last_timestamp"] = ts

        if rtype == "session_meta":
            metrics["session_meta_records"] += 1
            project = project or extract_project(record)
            session_id = session_id or extract_session_id(record)
        elif rtype == "turn_context":
            metrics["turn_context_records"] += 1
            project = project or extract_project(record)
        elif rtype == "compacted":
            metrics["compacted_records"] += 1
            metrics["compacted_bytes"] += len(raw)
            metrics["latest_compacted_timestamp"] = ts or metrics["latest_compacted_timestamp"]
            replacement = replacement_history(record)
            if replacement is None:
                metrics["legacy_compacted_records"] += 1
                metrics["latest_compaction_has_replacement_history"] = False
                metrics["latest_compaction_installed"] = False
                metrics["latest_compaction_state"] = "legacy"
            else:
                replacement_bytes = len(
                    json.dumps(replacement, separators=(",", ":")).encode("utf-8")
                )
                metrics["latest_compaction_has_replacement_history"] = True
                metrics["latest_compaction_installed"] = True
                metrics["latest_compaction_state"] = "installed"
                metrics["installed_compaction_checkpoints"] += 1
                metrics["max_replacement_history_items"] = max(
                    metrics["max_replacement_history_items"],
                    len(replacement),
                )
                metrics["max_replacement_history_bytes"] = max(
                    metrics["max_replacement_history_bytes"],
                    replacement_bytes,
                )
        elif rtype == "response_item":
            metrics["response_items"] += 1
            if ptype == "message":
                metrics["response_messages"] += 1
            elif ptype == "compaction":
                metrics["compaction_request_items"] += 1
                metrics["compaction_items"] += 1
                metrics["latest_compaction_installed"] = False
                metrics["latest_compaction_state"] = "request-only"
            elif ptype == "context_compaction":
                metrics["compaction_request_items"] += 1
                metrics["compaction_items"] += 1
                metrics["context_compaction_items"] += 1
                metrics["latest_compaction_installed"] = False
                metrics["latest_compaction_state"] = "request-only"
            elif ptype == "compaction_trigger":
                metrics["compaction_request_items"] += 1
                metrics["compaction_triggers"] += 1
                metrics["latest_compaction_installed"] = False
                metrics["latest_compaction_state"] = "request-only"
        elif rtype == "event_msg":
            ptype = canonical_event_type(record)
            metrics["event_messages"] += 1
            if ptype == "context_compacted":
                metrics["context_compacted_events"] += 1
            elif ptype == "turn_started":
                metrics["turn_started_events"] += 1
                metrics["latest_turn_event"] = "turn_started"
                open_turn_events += 1
            elif ptype == "turn_complete":
                metrics["turn_complete_events"] += 1
                metrics["turn_terminal_events"] += 1
                metrics["latest_turn_event"] = "turn_complete"
                open_turn_events = max(0, open_turn_events - 1)
                metrics["recovered_turn_error_events"] += turn_error_events_since_last_success
                turn_error_events_since_last_success = 0
            elif ptype == "turn_aborted":
                metrics["turn_aborted_events"] += 1
                metrics["turn_terminal_events"] += 1
                metrics["latest_turn_event"] = "turn_aborted"
                open_turn_events = max(0, open_turn_events - 1)
                turn_error_events_since_last_success += 1
            elif ptype == "error":
                metrics["error_events"] += 1
                metrics["turn_terminal_events"] += 1
                metrics["latest_turn_event"] = "error"
                open_turn_events = max(0, open_turn_events - 1)
                turn_error_events_since_last_success += 1

        update_token_metrics(record, metrics)
        update_visual_metrics(record, line_no, metrics)

        text = record_text(record)
        if rtype == "event_msg" and text:
            event_type = canonical_event_type(record)
            lowered = text.lower()
            if event_type in {"error", "warning"} and any(
                term in lowered for term in COMPACTION_FAILURE_TERMS
            ):
                metrics["compaction_failures"].append(COMPACTION_FAILURE_DIAGNOSTIC)
            if any(term in lowered for term in LONG_THREAD_TERMS):
                metrics["long_thread_warnings"].append(LONG_THREAD_DIAGNOSTIC)

    if metrics["bytes"] > 0:
        metrics["compacted_payload_percent"] = round(
            (metrics["compacted_bytes"] / metrics["bytes"]) * 100,
            2,
        )
    metrics["unresolved_turn_error_events"] = turn_error_events_since_last_success
    metrics["incomplete_turn_events"] = open_turn_events
    integrity = integrity_accumulator.result()
    metrics["invalid_image_urls"] = integrity.invalid_image_urls
    metrics["invalid_image_urls_in_compacted_records"] = (
        integrity.invalid_image_urls_in_compacted_records
    )
    metrics["remote_image_urls"] = integrity.remote_image_urls
    metrics["session_integrity_findings"] = (
        integrity.invalid_image_urls + integrity.remote_image_urls
    )
    metrics["history_base_present"] = integrity.history_base_present

    project = project or str(path.parent)
    risk_domains = build_risk_domains(metrics, thresholds)
    decision = decide_health(metrics, thresholds, risk_domains)
    task_state = task_state_for_metrics(metrics)
    notices = notices_for_domains(risk_domains)
    scale = scale_for_metrics(metrics, thresholds)
    continuation_risk = continuation_risk_for_domains(risk_domains, scale)
    handoff_lineage = base_handoff_lineage()
    action = action_for_state(task_state, continuation_risk, handoff_lineage)
    return {
        "file": str(path),
        "project": project,
        "session_id": session_id,
        "status": decision["status"],
        "continuation_status": decision["status"],
        "recommendation": decision["recommendation"],
        "overall_assessment": decision["overall_assessment"],
        "reasons": decision["reasons"],
        "risk_domains": risk_domains,
        "task_state": task_state,
        "notices": notices,
        "continuation_risk": continuation_risk,
        "handoff_readiness": handoff_readiness(metrics, decision),
        "scale": scale,
        "handoff_lineage": handoff_lineage,
        "action": action,
        "metrics": metrics,
    }


def build_risk_domains(
    metrics: dict[str, Any],
    thresholds: HealthThresholds,
) -> dict[str, dict[str, Any]]:
    return {
        "load": load_risk(metrics, thresholds),
        "visuals": visuals_risk(metrics, thresholds),
        "compaction": compaction_risk(metrics, thresholds),
        "limits": limits_risk(metrics, thresholds),
        "continuity": continuity_risk(metrics),
    }


def domain(status: str, evidence: list[str]) -> dict[str, Any]:
    return {"status": status, "evidence": evidence}


def load_risk(metrics: dict[str, Any], thresholds: HealthThresholds) -> dict[str, Any]:
    danger: list[str] = []
    warn: list[str] = []

    if metrics["bytes"] >= thresholds.danger_bytes:
        danger.append(
            f"session file is {metrics['bytes']} bytes, at or above danger threshold"
        )
    elif metrics["bytes"] >= thresholds.warn_bytes:
        warn.append(
            f"session file is {metrics['bytes']} bytes, at or above warning threshold"
        )

    if metrics["compacted_payload_percent"] > 50:
        danger.append("compacted records dominate the session file size")
    elif metrics["compacted_payload_percent"] > 25:
        warn.append("compacted records are more than 25% of session file size")

    if metrics["max_line_bytes"] >= 50 * 1024 * 1024:
        danger.append("one JSONL record is larger than 50 MB")
    elif metrics["max_line_bytes"] >= 5 * 1024 * 1024:
        warn.append("one JSONL record is larger than 5 MB")

    if danger:
        return domain("danger", danger + warn)
    if warn:
        return domain("warn", warn)
    return domain("ok", [])


def compaction_risk(metrics: dict[str, Any], thresholds: HealthThresholds) -> dict[str, Any]:
    danger: list[str] = []
    warn: list[str] = []

    if metrics["compaction_failures"]:
        danger.append("compaction failure or context-window error event was recorded")

    if (
        metrics["compacted_records"] > 0
        and not metrics["latest_compaction_has_replacement_history"]
    ):
        danger.append("latest compacted checkpoint lacks replacement_history")

    if (
        metrics["compaction_items"] > thresholds.max_healthy_compactions
        and metrics["long_thread_warnings"]
    ):
        danger.append("multiple compactions plus long-thread quality warning recorded")

    if metrics["legacy_compacted_records"] > 0:
        warn.append("legacy compacted records without replacement_history exist")

    if danger:
        return domain("danger", danger + warn)
    if warn:
        return domain("warn", warn)
    return domain("ok", [])


def visuals_risk(metrics: dict[str, Any], _thresholds: HealthThresholds) -> dict[str, Any]:
    danger: list[str] = []
    warn: list[str] = []

    if metrics["invalid_image_urls_in_compacted_records"] > 0:
        danger.append(
            "invalid model-visible image URL exists inside compacted replacement history"
        )
    elif metrics["invalid_image_urls"] > 0:
        danger.append("invalid model-visible image URL can break thread replay")

    if metrics["remote_image_urls"] > 0:
        danger.append("remote model-visible image URL is unsafe for thread replay")

    if metrics["visual_embedded_bytes"] >= 300 * 1024 * 1024:
        danger.append("embedded visual payloads exceed 300 MB")
    elif metrics["visual_embedded_bytes"] >= 50 * 1024 * 1024:
        warn.append("embedded visual payloads exceed 50 MB")

    if metrics["largest_visual_artifact_bytes"] >= 50 * 1024 * 1024:
        danger.append("one visual artifact is at least 50 MB")

    if metrics["bytes"] >= 512 * 1024 * 1024 and metrics["visual_embedded_artifacts"] > 0:
        danger.append("large session file contains embedded visual payloads")

    if metrics["visual_artifacts_in_compacted_records"] > 0:
        warn.append(COMPACTED_VISUAL_REFERENCE_DIAGNOSTIC)

    if metrics["visual_artifact_errors"] > 0:
        warn.append("some visual references could not be read or decoded")

    if danger:
        return domain("danger", danger + warn)
    if warn:
        return domain("warn", warn)
    return domain("ok", [])


def limits_risk(metrics: dict[str, Any], thresholds: HealthThresholds) -> dict[str, Any]:
    danger: list[str] = []
    warn: list[str] = []

    if metrics["response_items"] >= thresholds.danger_items:
        danger.append(
            f"response_items is {metrics['response_items']}, at or above danger threshold"
        )
    elif metrics["response_items"] >= thresholds.warn_items:
        warn.append(
            f"response_items is {metrics['response_items']}, at or above warning threshold"
        )

    if metrics["latest_token_ratio"] is not None:
        if metrics["latest_token_ratio"] >= 0.9:
            danger.append("active token estimate is above 90% of context window")
        elif metrics["latest_token_ratio"] >= 0.7:
            warn.append("active token estimate is above 70% of context window")

    if danger:
        return domain("danger", danger + warn)
    if warn:
        return domain("warn", warn)
    return domain("ok", [])


def continuity_risk(metrics: dict[str, Any]) -> dict[str, Any]:
    danger: list[str] = []
    warn: list[str] = []

    if metrics["unresolved_turn_error_events"] > 0:
        danger.append("unresolved turn abort or error event was recorded")
    elif metrics["recovered_turn_error_events"] > 0:
        warn.append(RECOVERED_CONTINUITY_WARNING_DIAGNOSTIC)
    if metrics["incomplete_turn_events"] > 0:
        warn.append(ACTIVE_TURN_DIAGNOSTIC)
    if metrics["session_meta_records"] == 0:
        danger.append("no session_meta record found")
    if (
        metrics["compacted_records"] > 0
        and metrics["turn_complete_events"] == 0
        and metrics["context_compacted_events"] == 0
    ):
        warn.append("compaction exists but no persisted completion event was found")

    if danger:
        return domain("danger", danger + warn)
    if warn:
        return domain("warn", warn)
    return domain("ok", [])


def decide_health(
    metrics: dict[str, Any],
    _thresholds: HealthThresholds,
    risk_domains: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    reasons: list[str] = []
    worst_status = "ok"
    for name, details in risk_domains.items():
        status = details["status"]
        if STATUS_RANK[status] > STATUS_RANK[worst_status]:
            worst_status = status
        for evidence in details["evidence"]:
            reasons.append(evidence)

    if worst_status == "danger":
        return {
            "status": "danger",
            "recommendation": "handoff-now",
            "overall_assessment": "handoff-now",
            "reasons": reasons,
        }
    if worst_status == "warn":
        return {
            "status": "warn",
            "recommendation": "monitor",
            "overall_assessment": "watch",
            "reasons": reasons,
        }
    return {
        "status": "ok",
        "recommendation": "continue",
        "overall_assessment": "continue",
        "reasons": [],
    }


def task_state_for_metrics(metrics: dict[str, Any]) -> dict[str, str]:
    if metrics["incomplete_turn_events"] > 0:
        return {
            "status": "active",
            "reason": "latest recorded turn has no terminal event",
        }
    if metrics["latest_turn_event"] == "turn_complete":
        return {
            "status": "completed",
            "reason": "latest recorded turn completed",
        }
    if metrics["latest_turn_event"] in {"turn_aborted", "error"}:
        return {
            "status": "interrupted",
            "reason": "latest recorded turn ended without completion",
        }
    return {
        "status": "unknown",
        "reason": "no tracked turn lifecycle event found",
    }


def notices_for_domains(
    risk_domains: dict[str, dict[str, Any]],
) -> list[str]:
    notices: list[str] = []
    for name in ("load", "visuals", "compaction", "limits", "continuity"):
        details = risk_domains.get(name)
        if not details:
            continue
        for evidence in details["evidence"]:
            if evidence in NOTICE_DIAGNOSTICS:
                notices.append(evidence)
    return dedupe(notices)


def continuation_risk_for_domains(
    risk_domains: dict[str, dict[str, Any]],
    scale: dict[str, str],
) -> dict[str, Any]:
    status = "ok"
    reasons: list[str] = []
    for name in ("load", "visuals", "compaction", "limits", "continuity"):
        details = risk_domains.get(name)
        if not details:
            continue
        relevant = [
            evidence
            for evidence in details["evidence"]
            if evidence not in NOTICE_DIAGNOSTICS
        ]
        reasons.extend(relevant)
        if relevant and STATUS_RANK[details["status"]] > STATUS_RANK[status]:
            status = details["status"]

    if scale["compactions"] == "watch":
        reasons.append(INSTALLED_COMPACTION_PRESSURE_DIAGNOSTIC)
        if STATUS_RANK["warn"] > STATUS_RANK[status]:
            status = "warn"

    return {
        "status": "watch" if status == "warn" else status,
        "reasons": dedupe(reasons),
    }


def scale_for_metrics(
    metrics: dict[str, Any],
    thresholds: HealthThresholds,
) -> dict[str, Any]:
    def threshold_status(value: int, warn: int, danger: int) -> str:
        if value >= danger:
            return "danger"
        if value >= warn:
            return "watch"
        return "ok"

    size = threshold_status(metrics["bytes"], thresholds.warn_bytes, thresholds.danger_bytes)
    items = threshold_status(
        metrics["response_items"],
        thresholds.warn_items,
        thresholds.danger_items,
    )
    compactions = "ok"
    if (
        metrics["installed_compaction_checkpoints"]
        > thresholds.max_healthy_compactions
    ):
        compactions = "watch"

    visuals = "ok"
    if metrics["invalid_image_urls_in_compacted_records"] > 0:
        visuals = "danger"
    elif metrics["invalid_image_urls"] > 0:
        visuals = "danger"
    elif metrics["remote_image_urls"] > 0:
        visuals = "danger"
    elif metrics["visual_embedded_bytes"] >= 300 * 1024 * 1024:
        visuals = "danger"
    elif metrics["largest_visual_artifact_bytes"] >= 50 * 1024 * 1024:
        visuals = "danger"
    elif metrics["bytes"] >= 512 * 1024 * 1024 and metrics["visual_embedded_artifacts"] > 0:
        visuals = "danger"
    elif metrics["visual_embedded_bytes"] >= 50 * 1024 * 1024:
        visuals = "watch"
    elif metrics["visual_artifact_errors"] > 0:
        visuals = "watch"
    elif metrics["visual_artifacts_in_compacted_records"] > 0:
        visuals = "notice"

    worst_status = "ok"
    for status in (size, items, compactions, visuals):
        if SCALE_RANK[status] > SCALE_RANK[worst_status]:
            worst_status = status

    return {
        "status": worst_status,
        "size": size,
        "items": items,
        "compactions": compactions,
        "visuals": visuals,
    }


def base_handoff_lineage() -> dict[str, Any]:
    return {
        "status": "not-recorded",
        "source_session_ids": [],
        "total_handoffs": 0,
    }


def action_for_state(
    task_state: dict[str, str],
    continuation_risk: dict[str, Any],
    handoff_lineage: dict[str, Any],
) -> dict[str, str]:
    ACTION_REASONS = {
        "continue": "no continuation risk requires a handoff",
        "finish-current-turn": (
            "task is active; no continuation risk requires a handoff"
        ),
        "prepare-handoff": (
            "continuation risk should be addressed with a deliberate handoff"
        ),
        "handoff-now": (
            "continuation risk requires a fresh thread before continuing"
        ),
        "use-replacement": (
            "this source session was retired by a completed handoff"
        ),
    }

    if handoff_lineage["status"] == "source-retired":
        status = "use-replacement"
    elif continuation_risk["status"] == "danger":
        status = "handoff-now"
    elif continuation_risk["status"] == "watch":
        status = "prepare-handoff"
    elif task_state["status"] == "active":
        status = "finish-current-turn"
    else:
        status = "continue"

    return {
        "status": status,
        "reason": ACTION_REASONS[status],
    }


def handoff_readiness(
    metrics: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    status = "not-needed"
    recommendation = "continue"
    reasons = list(decision["reasons"])

    if decision["status"] == "danger":
        status = "needed"
        recommendation = "handoff-now"
    elif decision["status"] == "warn":
        status = "recommended"
        recommendation = "prepare-handoff"

    visual_archive = "not-needed"
    if metrics["visual_artifacts"] > 0:
        visual_archive = "recommended"
        reasons.append("visual references should be archived before retiring this thread")

    return {
        "status": status,
        "recommendation": recommendation,
        "visual_archive": visual_archive,
        "reasons": dedupe(reasons),
    }


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def extract_project(record: dict[str, Any]) -> str:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return ""
    for key in ("cwd", "project_root", "workspace_root", "repo_root"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    config = payload.get("config")
    if isinstance(config, dict):
        for key in ("cwd", "project_root", "workspace_root"):
            value = config.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def extract_session_id(record: dict[str, Any]) -> str:
    payload = record.get("payload")
    if isinstance(payload, dict):
        value = payload.get("id") or payload.get("session_id")
        if isinstance(value, str):
            return value
    return ""


def canonical_event_type(record: dict[str, Any]) -> str:
    value = payload_type(record)
    return EVENT_TYPE_ALIASES.get(value, value)


def replacement_history(record: dict[str, Any]) -> list[Any] | None:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    value = payload.get("replacement_history")
    return value if isinstance(value, list) else None


def update_token_metrics(record: dict[str, Any], metrics: dict[str, Any]) -> None:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return
    info = payload.get("info")
    if not isinstance(info, dict):
        return
    total_usage = info.get("total_token_usage")
    last_usage = info.get("last_token_usage")
    if not isinstance(total_usage, dict):
        return
    total = total_usage.get("total_tokens")
    if not isinstance(total, int):
        return
    ts = record_timestamp(record)
    metrics["token_count_events"] += 1
    if ts and not metrics["first_token_timestamp"]:
        metrics["first_token_timestamp"] = ts
    if ts:
        metrics["latest_token_timestamp"] = ts
    active = last_usage.get("total_tokens") if isinstance(last_usage, dict) else None
    window = info.get("model_context_window")
    metrics["latest_token_usage"] = token_usage_fields(total_usage)
    if isinstance(last_usage, dict):
        metrics["latest_active_token_usage"] = token_usage_fields(last_usage)
    if isinstance(total, int):
        metrics["latest_token_total"] = total
    if isinstance(active, int):
        metrics["latest_active_token_total"] = active
    if isinstance(window, int):
        metrics["latest_model_context_window"] = window
    if isinstance(active, int) and isinstance(window, int) and window > 0:
        metrics["latest_token_ratio"] = round(active / window, 4)
    if isinstance(total, int) and isinstance(window, int) and window > 0:
        metrics["latest_cumulative_token_ratio"] = round(total / window, 4)


def update_visual_metrics(
    record: dict[str, Any],
    _line_no: int,
    metrics: dict[str, Any],
) -> None:
    visual_metrics = scan_record_visual_metrics(record)
    if visual_metrics["visual_artifacts"] == 0:
        return
    for key, value in visual_metrics.items():
        if key == "largest_visual_artifact_bytes":
            metrics[key] = max(metrics[key], value)
        else:
            metrics[key] += value
    if record.get("type") == "compacted":
        metrics["visual_artifacts_in_compacted_records"] += visual_metrics["visual_artifacts"]


def token_usage_fields(usage: dict[str, Any]) -> dict[str, int | None]:
    fields = (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    )
    return {
        field: usage[field] if isinstance(usage.get(field), int) else None
        for field in fields
    }


def active_sessions_by_project(session_root: Path) -> list[Path]:
    latest: dict[str, tuple[float, Path]] = {}
    for path in session_root.rglob("*.jsonl"):
        try:
            stat = path.stat()
            project = project_for_file(path)
        except OSError:
            continue
        current = latest.get(project)
        if current is None or stat.st_mtime > current[0]:
            latest[project] = (stat.st_mtime, path)
    return [item[1] for item in sorted(latest.values(), key=lambda item: str(item[1]))]


def session_files(session_root: Path) -> list[Path]:
    return sorted(path for path in session_root.rglob("*.jsonl") if path.is_file())


def project_for_file(path: Path) -> str:
    for _line_no, _raw, record in iter_jsonl(path):
        if record.get("type") in {"session_meta", "turn_context"}:
            project = extract_project(record)
            if project:
                return project
    return str(path.parent)


def assert_safe_test_root(path: Path) -> None:
    live_root = default_session_root().resolve()
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(live_root)
    except ValueError:
        return
    raise SystemExit(
        f"error: safe test mode refuses to read the live Codex session root: {resolved}"
    )


def exit_code_for_status(status: str) -> int:
    if status in {"ok", "retired"}:
        return 0
    if status == "warn":
        return 2
    if status == "danger":
        return 3
    return 1


def aggregate_project_results(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "projects": len(results),
        "ok": sum(1 for result in results if result["status"] == "ok"),
        "warn": sum(1 for result in results if result["status"] == "warn"),
        "danger": sum(1 for result in results if result["status"] == "danger"),
        "retired": sum(1 for result in results if result["status"] == "retired"),
    }


def token_usage_for_result(result: dict[str, Any]) -> dict[str, Any]:
    metrics = result["metrics"]
    token_ratio = metrics["latest_token_ratio"]
    active_context_percent = (
        round(token_ratio * 100, 2) if isinstance(token_ratio, (int, float)) else None
    )
    return {
        "project": result["project"],
        "file": result["file"],
        "session_id": result["session_id"],
        "lifetime_tokens": metrics["latest_token_total"],
        "active_tokens": metrics["latest_active_token_total"],
        "active_context_percent": active_context_percent,
        "model_context_window": metrics["latest_model_context_window"],
        "lifetime_context_multiple": metrics["latest_cumulative_token_ratio"],
        "token_count_events": metrics["token_count_events"],
        "first_token_timestamp": metrics["first_token_timestamp"],
        "latest_token_timestamp": metrics["latest_token_timestamp"],
        "latest_token_usage": metrics["latest_token_usage"],
        "latest_active_token_usage": metrics["latest_active_token_usage"],
        "status": result["status"],
        "recommendation": result["recommendation"],
    }


def project_token_usage_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        source = token_usage_for_result(result)
        grouped.setdefault(source["project"], []).append(source)

    projects = [
        project_token_usage(project, sources)
        for project, sources in grouped.items()
    ]
    projects.sort(
        key=lambda item: (
            item["lifetime_tokens"] is None,
            -(item["lifetime_tokens"] or 0),
            item["project"],
        )
    )
    session_sources = [
        source for project in projects for source in project["sources"]
    ]
    reported = [
        source["lifetime_tokens"]
        for source in session_sources
        if isinstance(source["lifetime_tokens"], int)
    ]
    return {
        "summary": {
            "projects": len(projects),
            "sessions": len(session_sources),
            "projects_with_token_usage": sum(
                1 for project in projects if project["lifetime_tokens"] is not None
            ),
            "sessions_with_token_usage": len(reported),
            "reported_lifetime_tokens": sum(reported),
        },
        "projects": projects,
        "note": (
            "Token totals come from Codex-persisted token_count events. "
            "Missing token_count events are reported as null."
        ),
    }


def project_token_usage(project: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    sources = sorted(sources, key=lambda source: source["file"])
    token_sources = [
        source for source in sources if isinstance(source["lifetime_tokens"], int)
    ]
    lifetime_tokens = (
        sum(source["lifetime_tokens"] for source in token_sources)
        if token_sources
        else None
    )
    latest_source = latest_token_source(token_sources)
    return {
        "project": project,
        "lifetime_tokens": lifetime_tokens,
        "sessions": len(sources),
        "sessions_with_token_usage": len(token_sources),
        "latest_token_timestamp": latest_source["latest_token_timestamp"]
        if latest_source
        else "",
        "latest_active_tokens": latest_source["active_tokens"] if latest_source else None,
        "latest_active_context_percent": latest_source["active_context_percent"]
        if latest_source
        else None,
        "latest_model_context_window": latest_source["model_context_window"]
        if latest_source
        else None,
        "latest_file": latest_source["file"] if latest_source else sources[-1]["file"],
        "sources": sources,
    }


def latest_token_source(sources: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not sources:
        return None
    return max(sources, key=lambda source: source["latest_token_timestamp"] or "")


def _iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _age_minutes(mtime: float) -> float:
    return round((datetime.now(timezone.utc).timestamp() - mtime) / 60, 2)
