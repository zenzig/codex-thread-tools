#!/usr/bin/env python3
"""Read-only Codex session health analyzer."""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codex_thread_tools import __version__
from codex_thread_tools.remote_health import (
    RemoteHealthError,
    add_remote_metadata,
    build_remote_safe_report,
    run_remote_health,
    select_remote_project,
)
from codex_thread_tools.sessionlib import die, expand_path
from codex_thread_tools.sessionpaths import default_session_root
from codex_thread_tools.display import (
    format_bytes,
    format_count,
    format_project,
    render_table,
    truncate_middle,
)
from codex_thread_tools.handoff_markers import (
    annotate_result_with_handoff_context,
    default_marker_file,
    load_handoff_markers,
    marker_aware_active_sessions_by_project,
    replacement_prompt_markers,
)
from codex_thread_tools.thread_health import (
    HealthThresholds,
    aggregate_project_results,
    analyze_session_file,
    assert_safe_test_root,
    exit_code_for_status,
    project_token_usage_report,
    session_files,
    thresholds_from_env,
)


def apply_threshold_overrides(args: argparse.Namespace) -> HealthThresholds:
    base = thresholds_from_env()
    return HealthThresholds(
        warn_bytes=args.warn_bytes if args.warn_bytes is not None else base.warn_bytes,
        danger_bytes=args.danger_bytes
        if args.danger_bytes is not None
        else base.danger_bytes,
        warn_items=args.warn_items if args.warn_items is not None else base.warn_items,
        danger_items=args.danger_items
        if args.danger_items is not None
        else base.danger_items,
        max_healthy_compactions=args.max_healthy_compactions
        if args.max_healthy_compactions is not None
        else base.max_healthy_compactions,
    )


def status_label(status: str) -> str:
    return status.upper()


def next_step(status: str) -> str:
    if status == "danger":
        return "Create a handoff and start a fresh Codex thread before continuing."
    if status == "warn":
        return "You can continue, but make a handoff soon if this task will keep growing."
    if status == "retired":
        return "Use the active replacement thread or the handoff file."
    return "Continue in the current thread."


def handoff_label(value: str) -> str:
    labels = {
        "needed": "Needed",
        "recommended": "Recommended",
        "not-needed": "Not needed",
        "completed": "Completed",
    }
    return labels.get(value, status_label(value))


REMOTE_STATE_UNAVAILABLE = "Unavailable from this remote host"
REMOTE_STATE_UPDATE_MESSAGE = (
    "Update the remote codex-thread-tools installation for state-first details."
)


def task_state_line(item: dict[str, Any]) -> str:
    details = item.get("task_state")
    if not isinstance(details, dict):
        return f"Task: {REMOTE_STATE_UNAVAILABLE}"
    status = details.get("status", "unknown")
    reason = details.get("reason", "")
    label = status_label(str(status)).title()
    if reason:
        return f"Task: {label} - {reason}"
    return f"Task: {label}"


def continuation_line(item: dict[str, Any]) -> str:
    details = item.get("continuation_risk")
    if not isinstance(details, dict):
        return f"Continuation: {REMOTE_STATE_UNAVAILABLE}"
    return f"Continuation: {status_label(details.get('status', 'ok'))}"


def lineage_line(item: dict[str, Any]) -> str:
    details = item.get("handoff_lineage")
    if not isinstance(details, dict):
        return f"Handoff: {REMOTE_STATE_UNAVAILABLE}"
    status = str(details.get("status", "not-recorded"))
    labels = {
        "not-recorded": "Not recorded",
        "replacement-active": "Replacement active",
        "incomplete": "Incomplete replacement",
        "source-retired": "Source retired",
    }
    return f"Handoff: {labels.get(status, status_label(status).title())}"


def action_sentence(status: str) -> str:
    return {
        "continue": "Continue in the current thread.",
        "finish-current-turn": "Finish the current turn, then continue.",
        "prepare-handoff": (
            "Finish the current turn and prepare a deliberate handoff."
        ),
        "handoff-now": (
            "Create a handoff and start a fresh Codex thread before continuing."
        ),
        "use-replacement": "Use the active replacement thread or the handoff file.",
    }[status]


def action_line(item: dict[str, Any]) -> str:
    details = item.get("action")
    if not isinstance(details, dict):
        return f"Action: {REMOTE_STATE_UNAVAILABLE}"
    return f"Action: {action_sentence(str(details.get('status', 'continue')))}"


def scale_lines(
    item: dict[str, Any],
    size_format: str,
    thresholds: HealthThresholds | None = None,
) -> list[str]:
    details = item.get("scale")
    if not isinstance(details, dict):
        return ["Scale", f"  {REMOTE_STATE_UNAVAILABLE}"]
    metrics = item.get("metrics")
    if not isinstance(metrics, dict):
        return ["Scale", f"  {REMOTE_STATE_UNAVAILABLE}"]
    installed_compactions = metrics.get("installed_compaction_checkpoints")
    compaction_value = format_count(
        installed_compactions
        if isinstance(installed_compactions, int)
        and not isinstance(installed_compactions, bool)
        else None
    )
    compaction_line = f"  Compactions: {compaction_value}"
    if thresholds is not None and compaction_value != "not recorded":
        compaction_line += (
            f" of {format_count(thresholds.max_healthy_compactions)} healthy maximum"
        )
    size_line = f"  Size: {format_bytes(metrics['bytes'], size_format)}"
    items_line = f"  Items: {format_count(metrics['response_items'])}"
    if thresholds is not None:
        size_line += (
            f" of {format_bytes(thresholds.warn_bytes, size_format)} warning threshold"
        )
        items_line += (
            f" of {format_count(thresholds.warn_items)} warning threshold"
        )
    return [
        "Scale",
        f"  Status: {status_label(str(details.get('status', 'ok')))}",
        size_line,
        items_line,
        compaction_line,
        f"  Visuals: {format_count(metrics['visual_artifacts'])}",
    ]


def notice_lines(item: dict[str, Any]) -> list[str]:
    notices = item.get("notices")
    if notices is None:
        return ["Notices", f"  {REMOTE_STATE_UNAVAILABLE}"]
    if not notices:
        return ["Notices", "  none"]
    return ["Notices", *[f"  - {note}" for note in notices]]


def project_action_label(item: dict[str, Any]) -> str:
    if "action" not in item:
        return REMOTE_STATE_UNAVAILABLE
    action = item.get("action")
    if not isinstance(action, dict):
        return REMOTE_STATE_UNAVAILABLE
    status = str(action.get("status", "continue"))
    return {
        "continue": "Continue",
        "finish-current-turn": "Finish turn",
        "prepare-handoff": "Prepare handoff",
        "handoff-now": "Handoff now",
        "use-replacement": "Use replacement",
    }.get(status, status_label(status).title())


def project_task_line(item: dict[str, Any]) -> str:
    details = item.get("task_state")
    if not isinstance(details, dict):
        return REMOTE_STATE_UNAVAILABLE
    status = details.get("status", "unknown")
    reason = details.get("reason")
    if reason:
        return f"{status_label(str(status)).title()} - {reason}"
    return status_label(str(status)).title()


def project_scale_label(item: dict[str, Any]) -> str:
    scale = item.get("scale")
    if not isinstance(scale, dict):
        return REMOTE_STATE_UNAVAILABLE
    return status_label(str(scale.get("status", "ok")))


def continuation_label(item: dict[str, Any]) -> str:
    details = item.get("continuation_risk")
    if not isinstance(details, dict):
        return REMOTE_STATE_UNAVAILABLE
    return status_label(str(details.get("status", "ok")))


def project_lineage_label(item: dict[str, Any]) -> str:
    details = item.get("handoff_lineage")
    if not isinstance(details, dict):
        return REMOTE_STATE_UNAVAILABLE
    status = str(details.get("status", "not-recorded"))
    labels = {
        "not-recorded": "Not recorded",
        "replacement-active": "Replacement active",
        "incomplete": "Incomplete replacement",
        "source-retired": "Source retired",
    }
    return labels.get(status, status_label(status))


def is_missing_protocol_state_axes(item: dict[str, Any]) -> bool:
    return (
        not isinstance(item.get("task_state"), dict)
        and not isinstance(item.get("continuation_risk"), dict)
        and not isinstance(item.get("scale"), dict)
        and not isinstance(item.get("notices"), list)
        and not isinstance(item.get("handoff_lineage"), dict)
        and not isinstance(item.get("action"), dict)
    )


def is_remote_protocol_no_state_axes(result: dict[str, Any]) -> bool:
    if result.get("source") != "remote":
        return False
    projects = result.get("projects")
    if not isinstance(projects, list):
        return False
    return bool(projects) and all(
        is_missing_protocol_state_axes(item) for item in projects
    )


def remote_state_axes_are_missing(result: dict[str, Any]) -> bool:
    if result.get("source") != "remote":
        return False
    projects = result.get("projects")
    if not isinstance(projects, list) or not projects:
        return False
    return any(is_missing_protocol_state_axes(item) for item in projects)


def should_render_action_summary(item: dict[str, Any]) -> bool:
    continuation = item.get("continuation_risk", {}).get("status")
    if continuation in {"watch", "danger"}:
        return True
    lineage = item.get("handoff_lineage", {}).get("status")
    if lineage in {"incomplete", "source-retired"}:
        return True
    return False


def domain_lines(risk_domains: dict[str, dict[str, Any]], indent: str = "") -> list[str]:
    lines = [f"{indent}Domain risks:"]
    for name in ("load", "visuals", "compaction", "limits", "continuity"):
        details = risk_domains.get(name)
        if not details:
            continue
        label = name.replace("_", " ").title()
        lines.append(f"{indent}  {label}: {status_label(details['status'])}")
        for evidence in details.get("evidence", [])[:2]:
            lines.append(f"{indent}    - {evidence}")
    return lines


def format_reasons(reasons: list[str], indent: str = "  ") -> list[str]:
    if not reasons:
        return [f"{indent}Why: no risk signals found"]
    return [f"{indent}Why: {reason}" for reason in reasons[:3]]


def maybe_pretty(
    result: dict[str, Any],
    fmt: str,
    mode: str = "standard",
    size_format: str = "bytes",
    thresholds: HealthThresholds | None = None,
) -> str:
    if fmt == "json":
        return json.dumps(result, indent=2)
    if result.get("report_type") == "token_usage":
        return tokens_pretty(result, mode=mode, size_format=size_format)
    if "projects" in result:
        return projects_pretty(
            result,
            mode=mode,
            size_format=size_format,
            thresholds=thresholds,
        )
    return check_pretty(
        result,
        mode=mode,
        size_format=size_format,
        thresholds=thresholds,
    )


def projects_pretty(
    result: dict[str, Any],
    mode: str,
    size_format: str,
    thresholds: HealthThresholds | None = None,
) -> str:
    summary = result["summary"]
    lines = ["Codex Thread Health"]
    if result.get("source") == "remote":
        lines.extend(["Source: REMOTE", f"Host: {result['host']}"])
    lines.extend(
        [
            f"Session folder: {result['session_root']}",
            f"Projects: {format_count(summary['projects'])}",
        ]
    )
    remote_protocol_without_state_axes = is_remote_protocol_no_state_axes(result)
    remote_state_axes_missing = remote_state_axes_are_missing(result)

    if mode == "verbose":
        if result["projects"]:
            lines.extend(["", "Attention Required"])
            for item in result["projects"]:
                lines.extend(
                    project_detail_lines(
                        item,
                        size_format=size_format,
                        thresholds=thresholds,
                    )
                )
                lines.append("")
        return "\n".join(lines).rstrip()

    if remote_protocol_without_state_axes:
        lines.extend(
            [
                "",
                "Current State",
                task_state_line(result["projects"][0]),
                continuation_line(result["projects"][0]),
                lineage_line(result["projects"][0]),
                action_line(result["projects"][0]),
                "Update the remote codex-thread-tools installation for state-first details.",
            ]
        )

    lines.extend(["", "Project Summary"])
    lines.extend(
        render_project_table(
            result["projects"],
            size_format,
        )
    )
    if mode == "compact":
        if remote_state_axes_missing:
            lines.append("Update the remote codex-thread-tools installation for state-first details.")
        return "\n".join(lines)

    if remote_state_axes_missing:
        lines.append("Update the remote codex-thread-tools installation for state-first details.")

    detail_items = [
        item for item in result["projects"] if should_render_action_summary(item)
    ]
    if detail_items:
        lines.extend(["", "Action Summary"])
        lines.extend(render_action_summary(detail_items))
    return "\n".join(lines).rstrip()


def check_pretty(
    result: dict[str, Any],
    mode: str,
    size_format: str,
    thresholds: HealthThresholds | None = None,
) -> str:
    if mode == "verbose":
        return check_verbose(
            result,
            size_format=size_format,
            thresholds=thresholds,
        )

    lines = [
        "Codex Thread Health",
        "Current State",
        task_state_line(result),
        continuation_line(result),
        lineage_line(result),
        action_line(result),
        "",
    ]
    lines.extend(scale_lines(result, size_format, thresholds))
    lines.extend(notice_lines(result))
    if mode != "compact":
        continuation = result.get("continuation_risk")
        if isinstance(continuation, dict):
            reasons = continuation.get("reasons")
            if isinstance(reasons, list) and reasons:
                lines.extend(format_reasons(reasons, indent=""))
    return "\n".join(lines)


def check_verbose(
    result: dict[str, Any],
    size_format: str,
    thresholds: HealthThresholds | None = None,
) -> str:
    lines = [
        "Codex Thread Health",
        f"Overall: {status_label(result['status'])}",
        f"Recommendation: {result['recommendation']}",
        f"Next step: {next_step(result['status'])}",
        task_state_line(result),
        continuation_line(result),
        lineage_line(result),
        action_line(result),
        *scale_lines(result, size_format, thresholds),
        *notice_lines(result),
        f"Continuation health: {status_label(result.get('continuation_status', result['status']))}",
        (
            "Handoff readiness: "
            f"{handoff_label(result.get('handoff_readiness', {}).get('status', ''))}"
        ),
        handoff_summary_line(result),
        replacement_line(result),
        retired_line(result),
        underlying_health_line(result),
        f"Project: {result['project']}",
        f"File: {result['file']}",
        f"Size: {size_summary(result['metrics'], size_format)}",
    ]
    if result["status"] != "retired":
        lines.extend(domain_lines(result.get("risk_domains", {})))
    lines.extend(format_reasons(result["reasons"], indent=""))
    return "\n".join(line for line in lines if line)


def render_project_table(
    projects: list[dict[str, Any]],
    size_format: str,
) -> list[str]:
    rows = []
    for item in projects:
        rows.append(
            [
                format_project(item["project"], 24),
                project_task_line(item),
                continuation_label(item),
                project_lineage_label(item),
                project_action_label(item),
                project_scale_label(item),
            ]
        )
    return render_table(
        (
            "Project",
            "Task",
            "Continue",
            "Lineage",
            "Action",
            "Scale",
        ),
        rows,
    )


def project_detail_lines(
    item: dict[str, Any],
    *,
    size_format: str,
    thresholds: HealthThresholds | None = None,
) -> list[str]:
    lines = [
        f"{status_label(item['status'])}: {item['project']}",
        f"  Overall: {status_label(item['status'])}",
        f"  Recommendation: {item['recommendation']}",
        f"  Next step: {next_step(item['status'])}",
        f"  {task_state_line(item)}",
        f"  {continuation_line(item)}",
        f"  {lineage_line(item)}",
        f"  {action_line(item)}",
        f"  Continuation health: {status_label(item.get('continuation_status', item['status']))}",
        (
            "  Handoff readiness: "
            f"{handoff_label(item.get('handoff_readiness', {}).get('status', ''))}"
        ),
    ]
    handoff_summary = item.get("handoff_summary", {})
    if handoff_summary.get("total_handoffs", 0):
        latest = handoff_summary.get("latest_handoff_at") or "unknown"
        lines.append(
            "  Handoffs: "
            f"{handoff_summary['total_handoffs']} total, latest {latest}"
        )
    if item.get("replaces_session_ids"):
        lines.append(f"  Replacement for: {', '.join(item['replaces_session_ids'])}")
    if item.get("retired_by_handoff"):
        lines.append("  Session role: Retired by handoff")
    lineage = item.get("handoff_lineage")
    if isinstance(lineage, dict) and lineage.get("source_session_ids"):
        lines.append(
            "  Lineage sources: "
            + ", ".join(str(value) for value in lineage["source_session_ids"])
        )
    if item.get("underlying_status"):
        lines.append(f"  Underlying health: {status_label(item['underlying_status'])}")
    lines.append(f"  Size: {size_summary(item['metrics'], size_format)}")
    lines.append(turn_events_line(item["metrics"], indent="  "))
    lines.extend(scale_lines(item, size_format, thresholds)[1:])
    lines.extend(notice_lines(item)[1:])
    if item["status"] != "retired":
        lines.extend(domain_lines(item.get("risk_domains", {}), indent="  "))
    lines.extend(format_reasons(item["reasons"]))
    lines.append(f"  File: {item['file']}")
    return lines


def render_action_summary(projects: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in projects:
        if lines:
            lines.append("")
        lines.append(f"{project_action_label(item)}: {format_project(item['project'], 56)}")
        reasons = action_reasons(item)
        for reason in reasons:
            lines.extend(wrap_bullet(reason, width=100, initial_indent="  - ", subsequent_indent="    "))
        if not reasons:
            lines.append("  - none")
    return lines


def action_for_item(item: dict[str, Any]) -> str:
    status = item["status"]
    if status == "danger":
        return "Handoff now"
    if status == "warn":
        return "Monitor"
    if status == "retired":
        return "Use replacement"
    if has_handoff_metadata(item):
        return "Continue"
    return "Continue"


def action_reasons(item: dict[str, Any]) -> list[str]:
    pieces: list[str] = []
    summary = item.get("handoff_summary", {})
    if summary.get("total_handoffs", 0):
        pieces.append(f"Handoffs: {summary['total_handoffs']} total")
    if item.get("replaces_session_ids"):
        pieces.append(f"Replacement for: {', '.join(item['replaces_session_ids'])}")
    if item.get("retired_by_handoff"):
        pieces.append("Retired by handoff")
    if item.get("underlying_status"):
        pieces.append(f"Underlying health: {status_label(item['underlying_status'])}")
    lineage = item.get("handoff_lineage")
    if isinstance(lineage, dict) and lineage.get("source_session_ids"):
        pieces.append(
            "Lineage sources: "
            + ", ".join(str(value) for value in lineage["source_session_ids"])
        )
    continuation = item.get("continuation_risk")
    if isinstance(continuation, dict):
        reasons = continuation.get("reasons")
        if isinstance(reasons, list):
            pieces.extend(reasons)
    return pieces


def wrap_bullet(
    value: str,
    *,
    width: int,
    initial_indent: str,
    subsequent_indent: str,
) -> list[str]:
    return textwrap.wrap(
        value,
        width=width,
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent,
        break_long_words=False,
        break_on_hyphens=False,
    )


def has_handoff_metadata(item: dict[str, Any]) -> bool:
    summary = item.get("handoff_summary", {})
    return bool(
        summary.get("total_handoffs", 0)
        or item.get("replaces_session_ids")
        or item.get("retired_by_handoff")
        or item.get("underlying_status")
    )


def render_domain_table(risk_domains: dict[str, dict[str, Any]]) -> list[str]:
    rows = []
    for name in ("load", "visuals", "compaction", "limits", "continuity"):
        details = risk_domains.get(name)
        if not details:
            continue
        evidence = "; ".join(details.get("evidence", [])[:2]) or "none"
        rows.append([name.replace("_", " ").title(), status_label(details["status"]), evidence])
    return render_table(("Domain", "Status", "Evidence"), rows)


def reason_bullets(reasons: list[str]) -> list[str]:
    if not reasons:
        return ["- no risk signals found"]
    return [f"- {reason}" for reason in reasons[:3]]


def size_summary(metrics: dict[str, Any], size_format: str) -> str:
    return (
        f"{format_bytes(metrics['bytes'], size_format)}, "
        f"{format_count(metrics['response_items'])} response items, "
        f"{format_count(metrics['compacted_records'])} compacted checkpoints, "
        f"{format_count(metrics['visual_artifacts'])} visual refs"
    )


def turn_events_line(metrics: dict[str, Any], *, indent: str = "") -> str:
    fields = (
        "turn_started_events",
        "turn_complete_events",
        "turn_aborted_events",
        "error_events",
        "turn_terminal_events",
        "incomplete_turn_events",
    )
    if not all(isinstance(metrics.get(field), int) for field in fields):
        return f"{indent}Turn events: not recorded"
    return (
        f"{indent}Turn events: {metrics['turn_started_events']} started, "
        f"{metrics['turn_complete_events']} completed, "
        f"{metrics['turn_aborted_events']} aborted, {metrics['error_events']} errors, "
        f"{metrics['turn_terminal_events']} terminal, "
        f"{metrics['incomplete_turn_events']} incomplete"
    )


def summary_status(summary: dict[str, int]) -> str:
    if summary["danger"]:
        return "danger"
    if summary["warn"]:
        return "warn"
    if summary.get("ok", 0):
        return "ok"
    if summary.get("retired", 0):
        return "retired"
    return "ok"


def handoff_summary_line(result: dict[str, Any]) -> str:
    summary = result.get("handoff_summary", {})
    if not summary.get("total_handoffs", 0):
        return ""
    latest = summary.get("latest_handoff_at") or "unknown"
    return f"Handoffs: {summary['total_handoffs']} total, latest {latest}"


def replacement_line(result: dict[str, Any]) -> str:
    replaces = result.get("replaces_session_ids") or []
    if not replaces:
        return ""
    return f"Replacement for: {', '.join(replaces)}"


def retired_line(result: dict[str, Any]) -> str:
    if not result.get("retired_by_handoff"):
        return ""
    return "Session role: Retired by handoff"


def underlying_health_line(result: dict[str, Any]) -> str:
    if "underlying_status" not in result:
        return ""
    return f"Underlying health: {status_label(result['underlying_status'])}"


def token_value(value: Any) -> str:
    return format_count(value)


def tokens_pretty(
    result: dict[str, Any],
    mode: str = "standard",
    size_format: str = "bytes",
) -> str:
    del size_format
    summary = result["summary"]
    lines = [
        "Codex Project Token Usage",
        f"Session folder: {result['session_root']}",
        (
            f"Projects: {format_count(summary['projects'])} "
            f"({format_count(summary['projects_with_token_usage'])} with token usage)"
        ),
        (
            f"Sessions: {format_count(summary['sessions'])} "
            f"({format_count(summary['sessions_with_token_usage'])} with token usage)"
        ),
        f"Reported lifetime tokens: {format_count(summary['reported_lifetime_tokens'])}",
        "Note: token totals come from Codex-persisted token_count events.",
        "",
    ]
    if mode != "verbose":
        lines.append("Project Token Summary")
        lines.extend(render_token_table(result["projects"]))
        return "\n".join(lines)

    for item in result["projects"]:
        active_percent = item["latest_active_context_percent"]
        active_text = (
            f"{active_percent}%"
            if isinstance(active_percent, (int, float))
            else "not recorded"
        )
        lines.append(item["project"])
        lines.append(f"  Lifetime tokens: {token_value(item['lifetime_tokens'])}")
        lines.append(f"  Sessions: {item['sessions']} ({item['sessions_with_token_usage']} with token usage)")
        lines.append(f"  Latest active tokens: {token_value(item['latest_active_tokens'])}")
        lines.append(f"  Active context: {active_text}")
        token_events = sum(source["token_count_events"] for source in item["sources"])
        lines.append(f"  Token events: {format_count(token_events)}")
        if item["latest_token_timestamp"]:
            lines.append(f"  Latest token event: {item['latest_token_timestamp']}")
        lines.append(f"  Latest file: {item['latest_file']}")
        lines.append("")
    return "\n".join(lines)


def render_token_table(projects: list[dict[str, Any]]) -> list[str]:
    rows = []
    for item in projects:
        active_percent = item["latest_active_context_percent"]
        active_text = (
            f"{active_percent}%"
            if isinstance(active_percent, (int, float))
            else "not recorded"
        )
        token_events = sum(source["token_count_events"] for source in item["sources"])
        rows.append(
            [
                format_project(item["project"], 46),
                token_value(item["lifetime_tokens"]),
                f"{format_count(item['sessions'])} ({format_count(item['sessions_with_token_usage'])})",
                token_value(item["latest_active_tokens"]),
                active_text,
                format_count(token_events),
            ]
        )
    return render_table(
        ("Project", "Lifetime", "Sessions", "Active", "Context", "Events"),
        rows,
    )


def ensure_file(path: Path) -> None:
    if not path.exists():
        die(f"session file does not exist: {path}")
    if not path.is_file():
        die(f"session path is not a file: {path}")


def check_command(args: argparse.Namespace) -> int:
    source = expand_path(args.session_file)
    if args.safe_test_mode:
        assert_safe_test_root(source)
    ensure_file(source)

    progress(args, f"Analyzing session: {source} ({format_bytes(source.stat().st_size, args.size_format)})")
    thresholds = apply_threshold_overrides(args)
    result = analyze_session_file(source, thresholds)
    markers = handoff_markers_for_args(args)
    replacements = replacement_prompt_markers([source])
    annotate_result_with_handoff_context(result, markers, replacements)
    print(
        maybe_pretty(
            result,
            args.format,
            args.mode,
            args.size_format,
            thresholds,
        )
    )
    return exit_code_for_status(result["status"])


def projects_command(args: argparse.Namespace) -> int:
    session_root = expand_path(args.session_root)
    if args.safe_test_mode:
        assert_safe_test_root(session_root)
    if not session_root.exists():
        die(f"session root does not exist: {session_root}")
    if not session_root.is_dir():
        die(f"session root is not a directory: {session_root}")

    thresholds = apply_threshold_overrides(args)
    markers = handoff_markers_for_args(args)
    progress(args, f"Finding active sessions under: {session_root}")
    paths = marker_aware_active_sessions_by_project(session_root, markers)
    replacements = replacement_prompt_markers(paths)
    progress(args, f"Analyzing {len(paths)} active project session(s)")
    projects = [
        analyze_with_progress(args, path, index, len(paths), thresholds)
        for index, path in enumerate(paths, 1)
    ]
    for project in projects:
        annotate_result_with_handoff_context(project, markers, replacements)
    summary = aggregate_project_results(projects)
    result = {"session_root": str(session_root), "summary": summary, "projects": projects}
    if args.remote_safe_json:
        print(json.dumps(build_remote_safe_report(result), indent=2))
    else:
        print(
            maybe_pretty(
                result,
                args.format,
                args.mode,
                args.size_format,
                thresholds,
            )
        )
    if summary["danger"]:
        return 3
    if summary["warn"]:
        return 2
    return 0


def tokens_command(args: argparse.Namespace) -> int:
    session_root = expand_path(args.session_root)
    if args.safe_test_mode:
        assert_safe_test_root(session_root)
    if not session_root.exists():
        die(f"session root does not exist: {session_root}")
    if not session_root.is_dir():
        die(f"session root is not a directory: {session_root}")

    thresholds = apply_threshold_overrides(args)
    progress(args, f"Finding session files under: {session_root}")
    paths = session_files(session_root)
    progress(args, f"Analyzing {len(paths)} session file(s) for token usage")
    project_results = [
        analyze_with_progress(args, path, index, len(paths), thresholds)
        for index, path in enumerate(paths, 1)
    ]
    result = project_token_usage_report(project_results)
    result["report_type"] = "token_usage"
    result["session_root"] = str(session_root)
    print(maybe_pretty(result, args.format, args.mode, args.size_format))
    return 0


def remote_threshold_args(args: argparse.Namespace) -> list[str]:
    result: list[str] = []
    for name in (
        "warn_bytes",
        "danger_bytes",
        "warn_items",
        "danger_items",
        "max_healthy_compactions",
    ):
        value = getattr(args, name)
        if value is not None:
            result.extend([f"--{name.replace('_', '-')}", str(value)])
    return result


def remote_command(args: argparse.Namespace) -> int:
    report, _remote_code, version_warning = run_remote_health(
        args.host,
        ["health", "projects", *remote_threshold_args(args)],
        local_version=__version__,
        connect_timeout=args.connect_timeout,
    )
    selected = select_remote_project(report, args.project)
    result = add_remote_metadata(selected, args.host)
    if version_warning:
        print(f"Warning: {version_warning}", file=sys.stderr)
    print(
        maybe_pretty(
            result,
            args.format,
            args.mode,
            args.size_format,
        )
    )
    summary = result["summary"]
    if summary["danger"]:
        return 3
    if summary["warn"]:
        return 2
    return 0


def add_report_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--warn-bytes", type=int)
    parser.add_argument("--danger-bytes", type=int)
    parser.add_argument("--warn-items", type=int)
    parser.add_argument("--danger-items", type=int)
    parser.add_argument("--max-healthy-compactions", type=int)
    parser.add_argument("--format", choices=("json", "pretty"), default="pretty")
    parser.add_argument(
        "--mode",
        choices=("compact", "standard", "verbose"),
        default="standard",
        help="pretty output detail level; ignored for JSON output",
    )
    parser.add_argument(
        "--size-format",
        choices=("bytes", "human", "both"),
        default="bytes",
        help="size display for pretty output",
    )
    parser.add_argument(
        "--json",
        action="store_const",
        const="json",
        dest="format",
        help="print machine-readable JSON instead of the beginner-friendly report",
    )


def add_local_scan_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--safe-test-mode",
        action="store_true",
        help="refuse to read from ~/.codex/sessions; intended for fixture and scratch runs",
    )
    parser.add_argument(
        "--progress",
        choices=("auto", "always", "never"),
        default="auto",
        help="print progress to stderr while large session files are scanned",
    )
    parser.add_argument(
        "--handoff-marker-file",
        default=None,
        help="local JSONL sidecar with completed handoff markers",
    )


def handoff_markers_for_args(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.handoff_marker_file:
        return load_handoff_markers(expand_path(args.handoff_marker_file))
    if getattr(args, "safe_test_mode", False):
        return []
    return load_handoff_markers(default_marker_file())


def analyze_with_progress(
    args: argparse.Namespace,
    path: Path,
    index: int,
    total: int,
    thresholds: HealthThresholds,
) -> dict[str, Any]:
    progress(args, f"[{index}/{total}] {path} ({format_bytes(path.stat().st_size, args.size_format)})")
    return analyze_session_file(path, thresholds)


def progress(args: argparse.Namespace, message: str) -> None:
    mode = getattr(args, "progress", "auto")
    if mode == "never":
        return
    if mode == "auto" and not sys.stderr.isatty():
        return
    print(message, file=sys.stderr, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze read-only health of Codex session JSONL files."
    )
    subparsers = parser.add_subparsers(dest="command")

    check = subparsers.add_parser("check", help="analyze one session file")
    check.add_argument("session_file")
    add_report_args(check)
    add_local_scan_args(check)
    check.set_defaults(func=check_command)

    projects = subparsers.add_parser(
        "projects",
        help="analyze the most recently modified session for each project",
    )
    projects.add_argument(
        "--session-root",
        default=str(default_session_root()),
        help="Codex session root to scan",
    )
    add_report_args(projects)
    add_local_scan_args(projects)
    projects.add_argument(
        "--remote-safe-json",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    projects.set_defaults(func=projects_command)

    tokens = subparsers.add_parser(
        "tokens",
        help="report Codex-persisted lifetime token usage for each project",
    )
    tokens.add_argument(
        "--session-root",
        default=str(default_session_root()),
        help="Codex session root to scan",
    )
    add_report_args(tokens)
    add_local_scan_args(tokens)
    tokens.set_defaults(func=tokens_command)

    remote = subparsers.add_parser(
        "remote",
        help="analyze active project sessions on an SSH host",
    )
    remote.add_argument(
        "--host",
        required=True,
        help="OpenSSH destination or alias containing the remote Codex sessions",
    )
    remote.add_argument(
        "--project",
        help="exact remote project path to select from the active-project report",
    )
    remote.add_argument(
        "--connect-timeout",
        type=int,
        default=10,
        help="SSH connection timeout in seconds",
    )
    add_report_args(remote)
    remote.set_defaults(func=remote_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0].startswith("-"):
        argv = ["projects", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RemoteHealthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except SystemExit as exc:
        if isinstance(exc.code, str) and exc.code.startswith("error:"):
            print(exc.code, file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
