#!/usr/bin/env python3
"""Read-only Codex session health analyzer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codex_thread_tools.sessionlib import die, expand_path
from codex_thread_tools.sessionpaths import default_session_root
from codex_thread_tools.thread_health import (
    HealthThresholds,
    active_sessions_by_project,
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
    return "Continue in the current thread."


def handoff_label(value: str) -> str:
    labels = {
        "needed": "Needed",
        "recommended": "Recommended",
        "not-needed": "Not needed",
    }
    return labels.get(value, status_label(value))


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


def maybe_pretty(result: dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(result, indent=2)
    if result.get("report_type") == "token_usage":
        return tokens_pretty(result)
    if "projects" in result:
        summary = result["summary"]
        status = "danger" if summary["danger"] else "warn" if summary["warn"] else "ok"
        lines = [
            "Codex Thread Health",
            f"Session folder: {result['session_root']}",
            (
                f"Overall: {status_label(status)} "
                f"({summary['ok']} ok, {summary['warn']} warn, {summary['danger']} danger)"
            ),
            f"Next step: {next_step(status)}",
            "",
        ]
        for item in result["projects"]:
            lines.append(
                f"{status_label(item['status'])}: {item['project']}"
            )
            lines.append(f"  Recommendation: {item['recommendation']}")
            lines.append(f"  Continuation health: {status_label(item.get('continuation_status', item['status']))}")
            lines.append(
                "  Handoff readiness: "
                f"{handoff_label(item.get('handoff_readiness', {}).get('status', ''))}"
            )
            lines.append(
                "  Size: "
                f"{item['metrics']['bytes']} bytes, "
                f"{item['metrics']['response_items']} response items, "
                f"{item['metrics']['compacted_records']} compacted checkpoints, "
                f"{item['metrics']['visual_artifacts']} visual refs"
            )
            lines.extend(domain_lines(item.get("risk_domains", {}), indent="  "))
            lines.extend(format_reasons(item["reasons"]))
            lines.append(f"  File: {item['file']}")
            lines.append("")
        return "\n".join(lines)
    lines = [
        "Codex Thread Health",
        f"Overall: {status_label(result['status'])}",
        f"Recommendation: {result['recommendation']}",
        f"Next step: {next_step(result['status'])}",
        f"Continuation health: {status_label(result.get('continuation_status', result['status']))}",
        (
            "Handoff readiness: "
            f"{handoff_label(result.get('handoff_readiness', {}).get('status', ''))}"
        ),
        f"Project: {result['project']}",
        f"File: {result['file']}",
        (
            "Size: "
            f"{result['metrics']['bytes']} bytes, "
            f"{result['metrics']['response_items']} response items, "
            f"{result['metrics']['compacted_records']} compacted checkpoints, "
            f"{result['metrics']['visual_artifacts']} visual refs"
        ),
    ]
    lines.extend(domain_lines(result.get("risk_domains", {})))
    lines.extend(format_reasons(result["reasons"], indent=""))
    return "\n".join(lines)


def token_value(value: Any) -> str:
    if value is None:
        return "not recorded"
    return str(value)


def tokens_pretty(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "Codex Project Token Usage",
        f"Session folder: {result['session_root']}",
        (
            f"Projects: {summary['projects']} "
            f"({summary['projects_with_token_usage']} with token usage)"
        ),
        (
            f"Sessions: {summary['sessions']} "
            f"({summary['sessions_with_token_usage']} with token usage)"
        ),
        f"Reported lifetime tokens: {summary['reported_lifetime_tokens']}",
        "Note: token totals come from Codex-persisted token_count events.",
        "",
    ]
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
        lines.append(f"  Token events: {token_events}")
        if item["latest_token_timestamp"]:
            lines.append(f"  Latest token event: {item['latest_token_timestamp']}")
        lines.append(f"  Latest file: {item['latest_file']}")
        lines.append("")
    return "\n".join(lines)


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

    progress(args, f"Analyzing session: {source} ({source.stat().st_size} bytes)")
    result = analyze_session_file(source, apply_threshold_overrides(args))
    print(maybe_pretty(result, args.format))
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
    progress(args, f"Finding active sessions under: {session_root}")
    paths = active_sessions_by_project(session_root)
    progress(args, f"Analyzing {len(paths)} active project session(s)")
    projects = [
        analyze_with_progress(args, path, index, len(paths), thresholds)
        for index, path in enumerate(paths, 1)
    ]
    summary = aggregate_project_results(projects)
    result = {"session_root": str(session_root), "summary": summary, "projects": projects}
    print(maybe_pretty(result, args.format))
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
    print(maybe_pretty(result, args.format))
    return 0


def add_threshold_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--warn-bytes", type=int)
    parser.add_argument("--danger-bytes", type=int)
    parser.add_argument("--warn-items", type=int)
    parser.add_argument("--danger-items", type=int)
    parser.add_argument("--max-healthy-compactions", type=int)
    parser.add_argument(
        "--safe-test-mode",
        action="store_true",
        help="refuse to read from ~/.codex/sessions; intended for fixture and scratch runs",
    )
    parser.add_argument("--format", choices=("json", "pretty"), default="pretty")
    parser.add_argument(
        "--json",
        action="store_const",
        const="json",
        dest="format",
        help="print machine-readable JSON instead of the beginner-friendly report",
    )
    parser.add_argument(
        "--progress",
        choices=("auto", "always", "never"),
        default="auto",
        help="print progress to stderr while large session files are scanned",
    )


def analyze_with_progress(
    args: argparse.Namespace,
    path: Path,
    index: int,
    total: int,
    thresholds: HealthThresholds,
) -> dict[str, Any]:
    progress(args, f"[{index}/{total}] {path} ({path.stat().st_size} bytes)")
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
    add_threshold_args(check)
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
    add_threshold_args(projects)
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
    add_threshold_args(tokens)
    tokens.set_defaults(func=tokens_command)

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
    except SystemExit as exc:
        if isinstance(exc.code, str) and exc.code.startswith("error:"):
            print(exc.code, file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
