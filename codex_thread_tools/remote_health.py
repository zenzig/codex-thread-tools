"""SSH transport for remote Codex thread health reports."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from copy import deepcopy
from datetime import datetime
from typing import Any, Callable

from codex_thread_tools.thread_health import (
    ACTIVE_TURN_DIAGNOSTIC,
    COMPACTED_VISUAL_REFERENCE_DIAGNOSTIC,
    RECOVERED_CONTINUITY_WARNING_DIAGNOSTIC,
    TASK_STATES as VALID_TASK_STATES,
    CONTINUATION_RISK_STATES as VALID_CONTINUATION_RISK_STATES,
    SCALE_LEVELS as VALID_SCALE_LEVELS,
    HANDOFF_LINEAGE_STATES as VALID_HANDOFF_LINEAGE_STATES,
    ACTION_STATES as VALID_ACTION_STATES,
)


class RemoteHealthError(ValueError):
    """Expected remote-health operational failure."""


Runner = Callable[..., subprocess.CompletedProcess[str]]

VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CODEX_SESSION_ID_PATTERN = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
UTC_TIMESTAMP_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z$"
)
REMOTE_HEALTH_PROTOCOL = 1
SUMMARY_KEYS = ("projects", "ok", "warn", "danger", "retired")
REMOTE_REQUIRED_METRIC_KEYS = (
    "bytes",
    "response_items",
    "compacted_records",
    "visual_artifacts",
)
REMOTE_OPTIONAL_METRIC_KEYS = (
    "invalid_image_urls",
    "invalid_image_urls_in_compacted_records",
    "remote_image_urls",
    "session_integrity_findings",
)
REMOTE_METRIC_KEYS = REMOTE_REQUIRED_METRIC_KEYS + REMOTE_OPTIONAL_METRIC_KEYS
REMOTE_DOMAIN_KEYS = ("load", "visuals", "compaction", "limits", "continuity")
REQUIRED_PROJECT_KEYS = (
    "project",
    "file",
    "status",
    "continuation_status",
    "recommendation",
    "metrics",
    "reasons",
    "risk_domains",
    "handoff_readiness",
    "handoff_summary",
    "replaces_session_ids",
    "retired_by_handoff",
)
OPTIONAL_PROJECT_KEYS = (
    "underlying_status",
    "task_state",
    "continuation_risk",
    "scale",
    "notices",
    "handoff_lineage",
    "action",
)
STATE_DETAIL_FILTERED = "state detail omitted by remote privacy filter"
CANONICAL_TASK_STATE_REASONS = {
    "latest recorded turn has no terminal event",
    "latest recorded turn completed",
    "latest recorded turn ended without completion",
    "no tracked turn lifecycle event found",
}
CANONICAL_ACTION_REASONS = {
    "no continuation risk requires a handoff",
    "task is active; no continuation risk requires a handoff",
    "continuation risk should be addressed with a deliberate handoff",
    "continuation risk requires a fresh thread before continuing",
    "this source session was retired by a completed handoff",
}
CANONICAL_NOTICES = {
    ACTIVE_TURN_DIAGNOSTIC,
    COMPACTED_VISUAL_REFERENCE_DIAGNOSTIC,
    RECOVERED_CONTINUITY_WARNING_DIAGNOSTIC,
}
REPORT_KEYS = ("remote_health_protocol", "session_root", "summary", "projects")
STATUS_VALUES = {"ok", "warn", "danger", "retired"}
RECOMMENDATION_VALUES = {
    "continue",
    "monitor",
    "handoff-now",
    "use-replacement-thread",
}
HANDOFF_STATUS_VALUES = {"needed", "recommended", "not-needed", "completed"}
FILTERED_DIAGNOSTIC = "additional health signal omitted by remote privacy filter"
CANONICAL_DIAGNOSTICS = {
    "compacted records dominate the session file size",
    "compacted records are more than 25% of session file size",
    "one JSONL record is larger than 50 MB",
    "one JSONL record is larger than 5 MB",
    "compaction failure or context-window error event was recorded",
    "latest compacted checkpoint lacks replacement_history",
    "multiple compactions plus long-thread quality warning recorded",
    "legacy compacted records without replacement_history exist",
    "embedded visual payloads exceed 300 MB",
    "embedded visual payloads exceed 50 MB",
    "one visual artifact is at least 50 MB",
    "large session file contains embedded visual payloads",
    "visual references exist inside compacted replacement history",
    "some visual references could not be read or decoded",
    "invalid model-visible image URL can break thread replay",
    "invalid model-visible image URL exists inside compacted replacement history",
    "remote model-visible image URL is unsafe for thread replay",
    "active token estimate is above 90% of context window",
    "active token estimate is above 70% of context window",
    "unresolved turn abort or error event was recorded",
    "historical turn abort or error event was recovered by later completion",
    "active turn has no terminal completion, abort, or error event",
    "no session_meta record found",
    "compaction exists but no persisted completion event was found",
    "session was retired by completed handoff",
    FILTERED_DIAGNOSTIC,
}
CANONICAL_DIAGNOSTIC_PATTERNS = (
    re.compile(
        r"^session file is [0-9]+ bytes, at or above (?:danger|warning) threshold$"
    ),
    re.compile(
        r"^response_items is [0-9]+, at or above (?:danger|warning) threshold$"
    ),
)


def validate_ssh_destination(host: str) -> str:
    if not host or host.startswith("-"):
        raise RemoteHealthError("SSH host must be a non-empty destination")
    if any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in host
    ):
        raise RemoteHealthError("SSH host contains whitespace or control characters")
    return host


def build_ssh_argv(
    host: str,
    remote_args: list[str],
    *,
    connect_timeout: int = 10,
    ssh_executable: str = "ssh",
) -> list[str]:
    host = validate_ssh_destination(host)
    if connect_timeout < 1:
        raise RemoteHealthError("SSH connection timeout must be at least 1 second")
    return [
        ssh_executable,
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "--",
        host,
        shlex.join(remote_args),
    ]


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(value.strip())
    if not match:
        raise RemoteHealthError(f"invalid version returned by remote host: {value!r}")
    return tuple(int(part) for part in match.groups())


def ensure_compatible_versions(local_version: str, remote_version: str) -> str | None:
    local = _version_tuple(local_version)
    remote = _version_tuple(remote_version)
    if local[0] != remote[0]:
        raise RemoteHealthError(
            "incompatible remote version: "
            f"local {local_version}, remote {remote_version}; install matching major versions"
        )
    if local != remote:
        return f"remote version differs: local {local_version}, remote {remote_version}"
    return None


def _privacy_protocol_error() -> RemoteHealthError:
    return RemoteHealthError(
        "remote host does not support privacy-safe remote health protocol 1; "
        "upgrade codex-thread-tools on the remote host to the same version as local"
    )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_canonical_diagnostic(value: object) -> bool:
    return isinstance(value, str) and (
        value in CANONICAL_DIAGNOSTICS
        or any(pattern.fullmatch(value) for pattern in CANONICAL_DIAGNOSTIC_PATTERNS)
    )


def _is_canonical_state_detail(value: object, allowed: set[str]) -> bool:
    return (
        isinstance(value, str)
        and (value in allowed or value == STATE_DETAIL_FILTERED)
    )


def _is_enum(value: object, allowed: set[str]) -> bool:
    return isinstance(value, str) and value in allowed


def _is_codex_session_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and CODEX_SESSION_ID_PATTERN.fullmatch(value) is not None
    )


def _is_canonical_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not UTC_TIMESTAMP_PATTERN.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        return False
    return True


def _canonical_diagnostics(value: object) -> list[str]:
    if not isinstance(value, list):
        return [FILTERED_DIAGNOSTIC]
    result: list[str] = []
    for item in value:
        diagnostic = item if _is_canonical_diagnostic(item) else FILTERED_DIAGNOSTIC
        if diagnostic not in result:
            result.append(diagnostic)
    return result


def _enum(value: object, allowed: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise RemoteHealthError(f"cannot build remote-safe health report: invalid {field}")
    return value


def _state_detail(value: object, allowed: set[str]) -> str:
    if not _is_canonical_state_detail(value, allowed):
        return STATE_DETAIL_FILTERED
    return str(value)


def _nonnegative_int(value: object, field: str) -> int:
    if not _is_int(value):
        raise RemoteHealthError(f"cannot build remote-safe health report: invalid {field}")
    return value


def _project_summary(projects: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "projects": len(projects),
        "ok": sum(item["status"] == "ok" for item in projects),
        "warn": sum(item["status"] == "warn" for item in projects),
        "danger": sum(item["status"] == "danger" for item in projects),
        "retired": sum(item["status"] == "retired" for item in projects),
    }


def build_remote_safe_report(report: dict[str, Any]) -> dict[str, Any]:
    """Build the allowlisted report before any remote JSON serialization."""
    summary = report.get("summary")
    projects = report.get("projects")
    session_root = report.get("session_root")
    if not isinstance(summary, dict) or not isinstance(projects, list):
        raise RemoteHealthError("cannot build remote-safe health report: invalid report")
    if not isinstance(session_root, str):
        raise RemoteHealthError("cannot build remote-safe health report: invalid session_root")

    safe_projects: list[dict[str, Any]] = []
    for item in projects:
        if not isinstance(item, dict):
            raise RemoteHealthError("cannot build remote-safe health report: invalid project")
        project = item.get("project")
        file_path = item.get("file")
        if not isinstance(project, str) or not isinstance(file_path, str):
            raise RemoteHealthError(
                "cannot build remote-safe health report: invalid project identity"
            )
        metrics = item.get("metrics")
        risk_domains = item.get("risk_domains")
        readiness = item.get("handoff_readiness")
        handoff_summary = item.get("handoff_summary", {})
        replacements = item.get("replaces_session_ids", [])
        if not all(
            isinstance(value, dict)
            for value in (metrics, risk_domains, readiness, handoff_summary)
        ):
            raise RemoteHealthError(
                "cannot build remote-safe health report: invalid project diagnostics"
            )
        latest_handoff_at = handoff_summary.get("latest_handoff_at", "")

        safe_domains: dict[str, dict[str, Any]] = {}
        for name in REMOTE_DOMAIN_KEYS:
            details = risk_domains.get(name)
            if not isinstance(details, dict):
                raise RemoteHealthError(
                    "cannot build remote-safe health report: invalid risk domain"
                )
            safe_domains[name] = {
                "status": _enum(details.get("status"), STATUS_VALUES, "domain status"),
                "evidence": _canonical_diagnostics(details.get("evidence")),
            }

        safe_item: dict[str, Any] = {
            "project": project,
            "file": file_path,
            "status": _enum(item.get("status"), STATUS_VALUES, "status"),
            "continuation_status": _enum(
                item.get("continuation_status"),
                STATUS_VALUES,
                "continuation_status",
            ),
            "recommendation": _enum(
                item.get("recommendation"),
                RECOMMENDATION_VALUES,
                "recommendation",
            ),
            "metrics": {
                key: _nonnegative_int(
                    metrics.get(key, 0)
                    if key in REMOTE_OPTIONAL_METRIC_KEYS
                    else metrics.get(key),
                    f"metrics.{key}",
                )
                for key in REMOTE_METRIC_KEYS
            },
            "reasons": _canonical_diagnostics(item.get("reasons")),
            "risk_domains": safe_domains,
            "handoff_readiness": {
                "status": _enum(
                    readiness.get("status"),
                    HANDOFF_STATUS_VALUES,
                    "handoff_readiness.status",
                )
            },
            "handoff_summary": {
                "total_handoffs": _nonnegative_int(
                    handoff_summary.get("total_handoffs", 0),
                    "handoff_summary.total_handoffs",
                ),
                "latest_handoff_at": (
                    latest_handoff_at
                    if _is_canonical_utc_timestamp(latest_handoff_at)
                    else ""
                ),
            },
            "replaces_session_ids": [
                value
                for value in replacements
                if _is_codex_session_id(value)
            ]
            if isinstance(replacements, list)
            else [],
            "retired_by_handoff": bool(item.get("retired_by_handoff", False)),
        }
        if "underlying_status" in item:
            safe_item["underlying_status"] = _enum(
                item["underlying_status"], STATUS_VALUES, "underlying_status"
            )
        if "task_state" in item:
            task_state = item.get("task_state")
            if not isinstance(task_state, dict):
                raise RemoteHealthError(
                    "cannot build remote-safe health report: invalid task state"
                )
            safe_item["task_state"] = {
                "status": _enum(
                    task_state.get("status"),
                    set(VALID_TASK_STATES),
                    "task_state.status",
                ),
                "reason": _state_detail(
                    task_state.get("reason"), CANONICAL_TASK_STATE_REASONS
                ),
            }
        if "continuation_risk" in item:
            continuation_risk = item.get("continuation_risk")
            if not isinstance(continuation_risk, dict):
                raise RemoteHealthError(
                    "cannot build remote-safe health report: invalid continuation risk"
                )
            safe_item["continuation_risk"] = {
                "status": _enum(
                    continuation_risk.get("status"),
                    set(VALID_CONTINUATION_RISK_STATES),
                    "continuation_risk.status",
                ),
                "reasons": _canonical_diagnostics(continuation_risk.get("reasons")),
            }
        if "scale" in item:
            scale = item.get("scale")
            if not isinstance(scale, dict):
                raise RemoteHealthError(
                    "cannot build remote-safe health report: invalid scale"
                )
            safe_item["scale"] = {
                "status": _enum(scale.get("status"), set(VALID_SCALE_LEVELS), "scale.status"),
                "size": _enum(scale.get("size"), set(VALID_SCALE_LEVELS), "scale.size"),
                "items": _enum(scale.get("items"), set(VALID_SCALE_LEVELS), "scale.items"),
                "compactions": _enum(
                    scale.get("compactions"), set(VALID_SCALE_LEVELS), "scale.compactions"
                ),
                "visuals": _enum(
                    scale.get("visuals"), set(VALID_SCALE_LEVELS), "scale.visuals"
                ),
            }
        if "notices" in item:
            safe_item["notices"] = _canonical_diagnostics(item.get("notices"))
        if "handoff_lineage" in item:
            lineage = item.get("handoff_lineage")
            if not isinstance(lineage, dict):
                raise RemoteHealthError(
                    "cannot build remote-safe health report: invalid handoff lineage"
                )
            source_session_ids = lineage.get("source_session_ids", [])
            if not isinstance(source_session_ids, list):
                raise RemoteHealthError(
                    "cannot build remote-safe health report: invalid handoff lineage source ids"
                )
            safe_item["handoff_lineage"] = {
                "status": _enum(
                    lineage.get("status"),
                    set(VALID_HANDOFF_LINEAGE_STATES),
                    "handoff_lineage.status",
                ),
                "source_session_ids": [
                    value for value in source_session_ids if _is_codex_session_id(value)
                ],
                "total_handoffs": _nonnegative_int(
                    lineage.get("total_handoffs", 0),
                    "handoff_lineage.total_handoffs",
                ),
            }
        if "action" in item:
            action = item.get("action")
            if not isinstance(action, dict):
                raise RemoteHealthError(
                    "cannot build remote-safe health report: invalid action"
                )
            safe_item["action"] = {
                "status": _enum(
                    action.get("status"),
                    set(VALID_ACTION_STATES),
                    "action.status",
                ),
                "reason": _state_detail(
                    action.get("reason"), CANONICAL_ACTION_REASONS
                ),
            }
        safe_projects.append(safe_item)

    return {
        "remote_health_protocol": REMOTE_HEALTH_PROTOCOL,
        "session_root": session_root,
        "summary": {
            key: _nonnegative_int(summary.get(key), f"summary.{key}")
            for key in SUMMARY_KEYS
        },
        "projects": safe_projects,
    }


def validate_projects_report(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RemoteHealthError("invalid remote health report: expected a JSON object")
    if value.get("remote_health_protocol") != REMOTE_HEALTH_PROTOCOL:
        raise _privacy_protocol_error()
    if set(value) != set(REPORT_KEYS):
        raise RemoteHealthError("invalid remote health report: unexpected report fields")
    if not isinstance(value.get("session_root"), str):
        raise RemoteHealthError("invalid remote health report: missing session_root")
    summary = value.get("summary")
    if not isinstance(summary, dict) or set(summary) != set(SUMMARY_KEYS) or any(
        not _is_int(summary.get(key)) for key in SUMMARY_KEYS
    ):
        raise RemoteHealthError("invalid remote health report: invalid summary")
    projects = value.get("projects")
    if not isinstance(projects, list):
        raise RemoteHealthError("invalid remote health report: projects must be a list")
    for project in projects:
        if not isinstance(project, dict):
            raise RemoteHealthError("invalid remote health report: invalid project entry")
        keys = set(project)
        if any(key not in keys for key in REQUIRED_PROJECT_KEYS) or not keys.issubset(
            {*REQUIRED_PROJECT_KEYS, *OPTIONAL_PROJECT_KEYS}
        ):
            raise RemoteHealthError("invalid remote health report: invalid project fields")
        if not isinstance(project["project"], str) or not isinstance(project["file"], str):
            raise RemoteHealthError("invalid remote health report: invalid project identity")
        if not _is_enum(project["status"], STATUS_VALUES) or not _is_enum(
            project["continuation_status"], STATUS_VALUES
        ):
            raise RemoteHealthError("invalid remote health report: invalid project status")
        if not _is_enum(project["recommendation"], RECOMMENDATION_VALUES):
            raise RemoteHealthError("invalid remote health report: invalid recommendation")
        if "underlying_status" in project and not _is_enum(
            project["underlying_status"], STATUS_VALUES
        ):
            raise RemoteHealthError("invalid remote health report: invalid underlying status")
        if "task_state" in project:
            details = project["task_state"]
            if not isinstance(details, dict) or set(details) != {"status", "reason"}:
                raise RemoteHealthError("invalid remote health report: invalid task state")
            if not _is_enum(details["status"], set(VALID_TASK_STATES)):
                raise RemoteHealthError(
                    "invalid remote health report: invalid task_state status"
                )
            if not _is_canonical_state_detail(
                details["reason"], CANONICAL_TASK_STATE_REASONS
            ):
                raise RemoteHealthError(
                    "invalid remote health report: invalid task_state reason"
                )
        if "continuation_risk" in project:
            details = project["continuation_risk"]
            if (
                not isinstance(details, dict)
                or set(details) != {"status", "reasons"}
                or not _is_enum(details["status"], set(VALID_CONTINUATION_RISK_STATES))
                or not isinstance(details["reasons"], list)
                or any(not _is_canonical_diagnostic(value) for value in details["reasons"])
            ):
                raise RemoteHealthError(
                    "invalid remote health report: invalid continuation_risk"
                )
        if "scale" in project:
            details = project["scale"]
            if not isinstance(details, dict):
                raise RemoteHealthError("invalid remote health report: invalid scale")
            if set(details) != {"status", "size", "items", "compactions", "visuals"}:
                raise RemoteHealthError("invalid remote health report: invalid scale")
            if any(
                key not in set(VALID_SCALE_LEVELS)
                for key in (
                    details["status"],
                    details["size"],
                    details["items"],
                    details["compactions"],
                    details["visuals"],
                )
            ):
                raise RemoteHealthError("invalid remote health report: invalid scale")
        if "notices" in project:
            notices = project["notices"]
            if (
                not isinstance(notices, list)
                or any(
                    not _is_canonical_diagnostic(item) and item not in CANONICAL_NOTICES
                    for item in notices
                )
            ):
                raise RemoteHealthError("invalid remote health report: invalid notices")
        if "handoff_lineage" in project:
            details = project["handoff_lineage"]
            if (
                not isinstance(details, dict)
                or set(details) != {"status", "source_session_ids", "total_handoffs"}
                or not _is_enum(details["status"], set(VALID_HANDOFF_LINEAGE_STATES))
                or not _is_int(details["total_handoffs"])
                or details["total_handoffs"] < 0
                or not isinstance(details["source_session_ids"], list)
                or any(not _is_codex_session_id(item) for item in details["source_session_ids"])
            ):
                raise RemoteHealthError(
                    "invalid remote health report: invalid handoff_lineage"
                )
        if "action" in project:
            details = project["action"]
            if not isinstance(details, dict) or set(details) != {"status", "reason"}:
                raise RemoteHealthError("invalid remote health report: invalid action")
            if not _is_enum(details["status"], set(VALID_ACTION_STATES)):
                raise RemoteHealthError("invalid remote health report: invalid action")
            if not _is_canonical_state_detail(
                details["reason"], CANONICAL_ACTION_REASONS
            ):
                raise RemoteHealthError(
                    "invalid remote health report: invalid action reason"
                )
        metrics = project["metrics"]
        if (
            not isinstance(metrics, dict)
            or not set(REMOTE_REQUIRED_METRIC_KEYS).issubset(metrics)
            or not set(metrics).issubset(REMOTE_METRIC_KEYS)
            or any(not _is_int(metrics.get(key)) for key in metrics)
        ):
            raise RemoteHealthError("invalid remote health report: invalid metrics")
        reasons = project["reasons"]
        if not isinstance(reasons, list) or any(
            not _is_canonical_diagnostic(reason) for reason in reasons
        ):
            raise RemoteHealthError("invalid remote health report: invalid reasons")
        domains = project["risk_domains"]
        if not isinstance(domains, dict) or set(domains) != set(REMOTE_DOMAIN_KEYS):
            raise RemoteHealthError("invalid remote health report: invalid risk domains")
        for details in domains.values():
            if not isinstance(details, dict) or set(details) != {"status", "evidence"}:
                raise RemoteHealthError("invalid remote health report: invalid risk domain")
            if not _is_enum(details["status"], STATUS_VALUES):
                raise RemoteHealthError("invalid remote health report: invalid domain status")
            evidence = details["evidence"]
            if not isinstance(evidence, list) or any(
                not _is_canonical_diagnostic(item) for item in evidence
            ):
                raise RemoteHealthError("invalid remote health report: invalid evidence")
        readiness = project["handoff_readiness"]
        if (
            not isinstance(readiness, dict)
            or set(readiness) != {"status"}
            or not _is_enum(readiness["status"], HANDOFF_STATUS_VALUES)
        ):
            raise RemoteHealthError("invalid remote health report: invalid handoff readiness")
        handoff_summary = project["handoff_summary"]
        if (
            not isinstance(handoff_summary, dict)
            or set(handoff_summary) != {"total_handoffs", "latest_handoff_at"}
            or not _is_int(handoff_summary["total_handoffs"])
            or not isinstance(handoff_summary["latest_handoff_at"], str)
            or (
                handoff_summary["latest_handoff_at"] != ""
                and not _is_canonical_utc_timestamp(
                    handoff_summary["latest_handoff_at"]
                )
            )
        ):
            raise RemoteHealthError("invalid remote health report: invalid handoff summary")
        replacements = project["replaces_session_ids"]
        if not isinstance(replacements, list) or any(
            not _is_codex_session_id(item) for item in replacements
        ):
            raise RemoteHealthError("invalid remote health report: invalid replacement ids")
        if not isinstance(project["retired_by_handoff"], bool):
            raise RemoteHealthError("invalid remote health report: invalid retirement state")
    if summary != _project_summary(projects):
        raise RemoteHealthError(
            "invalid remote health report: summary does not match projects"
        )
    return value


def select_remote_project(
    report: dict[str, Any],
    project: str | None,
) -> dict[str, Any]:
    selected = deepcopy(report)
    if project is None:
        return selected
    projects = [item for item in selected["projects"] if item["project"] == project]
    if not projects:
        raise RemoteHealthError(f"remote project was not found: {project}")
    selected["projects"] = projects
    selected["summary"] = _project_summary(projects)
    return selected


def add_remote_metadata(report: dict[str, Any], host: str) -> dict[str, Any]:
    result = deepcopy(report)
    result["source"] = "remote"
    result["host"] = host
    return result


def _remote_stderr(result: subprocess.CompletedProcess[str]) -> str:
    value = result.stderr or ""
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    return str(value).strip()[:500]


def _run_ssh(
    host: str,
    remote_args: list[str],
    *,
    connect_timeout: int,
    ssh_executable: str,
    runner: Runner,
    operation: str,
    wall_timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    argv = build_ssh_argv(
        host,
        remote_args,
        connect_timeout=connect_timeout,
        ssh_executable=ssh_executable,
    )
    runner_kwargs: dict[str, Any] = {
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "check": False,
        "shell": False,
    }
    if wall_timeout is not None:
        runner_kwargs["timeout"] = wall_timeout
    try:
        return runner(argv, **runner_kwargs)
    except FileNotFoundError as exc:
        raise RemoteHealthError(
            f"SSH executable was not found: {ssh_executable}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        elapsed = wall_timeout if wall_timeout is not None else exc.timeout
        raise RemoteHealthError(
            f"{operation} timed out on {host} after {elapsed} seconds"
        ) from exc


def _login_shell_args(remote_args: list[str]) -> list[str]:
    return [
        "sh",
        "-c",
        'exec "${SHELL:-/bin/sh}" -lc "$1"',
        "codex-thread-tools-login",
        shlex.join(remote_args),
    ]


def _raise_remote_command_error(
    result: subprocess.CompletedProcess[str],
    host: str,
    *,
    command: str,
) -> None:
    if result.returncode == 255:
        raise RemoteHealthError(
            f"SSH command failed for {host}: {_remote_stderr(result)}"
        )
    if result.returncode == 127:
        raise RemoteHealthError(
            "remote codex-thread-tools is not installed or not available to "
            f"non-interactive SSH on {host}"
        )
    raise RemoteHealthError(
        f"remote {command} command failed on {host}: {_remote_stderr(result)}"
    )


def run_remote_health(
    host: str,
    remote_args: list[str],
    *,
    local_version: str,
    connect_timeout: int = 10,
    ssh_executable: str = "ssh",
    runner: Runner = subprocess.run,
) -> tuple[dict[str, Any], int, str | None]:
    use_login_shell = False
    version_args = ["codex-thread-tools", "--version"]
    version_result = _run_ssh(
        host,
        version_args,
        connect_timeout=connect_timeout,
        ssh_executable=ssh_executable,
        runner=runner,
        operation="remote version probe",
        wall_timeout=connect_timeout + 5,
    )
    if version_result.returncode == 127:
        use_login_shell = True
        version_result = _run_ssh(
            host,
            _login_shell_args(version_args),
            connect_timeout=connect_timeout,
            ssh_executable=ssh_executable,
            runner=runner,
            operation="remote login-shell version probe",
            wall_timeout=connect_timeout + 5,
        )
    if version_result.returncode != 0:
        _raise_remote_command_error(version_result, host, command="version")
    remote_version = version_result.stdout.strip()
    warning = ensure_compatible_versions(local_version, remote_version)

    health_args = deepcopy(remote_args)
    health_args.extend(("--remote-safe-json", "--progress", "never"))
    health_command = ["codex-thread-tools", *health_args]
    health_result = _run_ssh(
        host,
        _login_shell_args(health_command) if use_login_shell else health_command,
        connect_timeout=connect_timeout,
        ssh_executable=ssh_executable,
        runner=runner,
        operation="remote health analysis",
    )
    if health_result.returncode not in {0, 2, 3}:
        _raise_remote_command_error(health_result, host, command="health")

    try:
        report = json.loads(health_result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        if health_result.returncode == 2 and "remote-safe-json" in _remote_stderr(
            health_result
        ):
            raise _privacy_protocol_error() from exc
        raise RemoteHealthError(
            f"remote health command returned malformed JSON from {host}"
        ) from exc
    return validate_projects_report(report), health_result.returncode, warning
