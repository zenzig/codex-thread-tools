#!/usr/bin/env python3
"""Archive Codex and Claude Code session files to external storage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import agent_thread_tools.session_archive as session_archive
from agent_thread_tools.session_archive import (
    format_archive,
    format_plan,
    format_prune,
    format_verify,
)
from agent_thread_tools.sessionlib import expand_path, is_codex_running, open_claude_sessions
from agent_thread_tools.sessionpaths import AGENTS, default_agent, default_session_root


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.handler(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def selected_agent(args: argparse.Namespace) -> str:
    if args.agent:
        return args.agent
    if args.session_root:
        return session_archive.agent_for_root(expand_path(args.session_root))
    return default_agent()


def selected_root(args: argparse.Namespace, agent: str) -> Path:
    return expand_path(args.session_root or default_session_root(agent))


def handle_plan(args: argparse.Namespace) -> int:
    agent = selected_agent(args)
    result = session_archive.build_archive_plan(
        session_root=selected_root(args, agent),
        project=args.project,
        older_than=args.older_than,
        min_size=args.min_size,
        now=args.now,
        open_session_ids=open_claude_sessions() if agent == "claude" else None,
        agent=agent,
    )
    emit(result, args.json, format_plan)
    return 0


def handle_archive(args: argparse.Namespace) -> int:
    agent = selected_agent(args)
    result = session_archive.archive_sessions(
        session_root=selected_root(args, agent),
        archive_root=expand_path(args.archive_root),
        project=args.project,
        older_than=args.older_than,
        min_size=args.min_size,
        archive_name=args.archive_name,
        now=args.now,
        force=args.force,
        open_session_ids=open_claude_sessions() if agent == "claude" else None,
        agent=agent,
    )
    emit(result, args.json, format_archive)
    return 0


def handle_verify(args: argparse.Namespace) -> int:
    result = session_archive.verify_archive(expand_path(args.manifest))
    emit(result, args.json, format_verify)
    return 3 if result["summary"]["failed"] else 0


def handle_prune(args: argparse.Namespace) -> int:
    manifest = session_archive.load_manifest(expand_path(args.manifest))
    if manifest.get("agent") == "claude":
        # Claude Code records each open session, so only those sessions are refused.
        result = session_archive.prune_local_sessions(
            manifest_file=expand_path(args.manifest),
            confirm_prune_local=args.confirm_prune_local,
            open_session_ids=open_claude_sessions(),
        )
        emit(result, args.json, format_prune)
        return 3 if result["summary"].get("failed_count", 0) else 0
    if is_codex_running() and not args.allow_codex_running:
        print(
            "error: Codex appears to be running. Quit Codex before pruning local "
            "session files, or pass --allow-codex-running if you have verified "
            "this is safe.",
            file=sys.stderr,
        )
        return 1
    result = session_archive.prune_local_sessions(
        manifest_file=expand_path(args.manifest),
        confirm_prune_local=args.confirm_prune_local,
    )
    emit(result, args.json, format_prune)
    return 3 if result["summary"].get("failed_count", 0) else 0


def emit(
    result: dict[str, Any],
    as_json: bool,
    formatter: Callable[[dict[str, Any]], str],
) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(formatter(result))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-thread-tools session-archive",
        description="Archive old Codex and Claude Code session files to external storage."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser(
        "plan",
        help="preview session files selected for archive",
    )
    add_selection_args(plan)
    add_json_arg(plan)
    plan.set_defaults(handler=handle_plan)

    archive = subparsers.add_parser(
        "archive",
        help="copy selected session files and write a manifest",
    )
    add_selection_args(archive)
    archive.add_argument(
        "--archive-root",
        required=True,
        help="external archive root outside the session root",
    )
    archive.add_argument(
        "--archive-name",
        help="archive folder name under <agent>-session-archives",
    )
    archive.add_argument(
        "--force",
        action="store_true",
        help="allow writing into an existing archive folder",
    )
    add_json_arg(archive)
    archive.set_defaults(handler=handle_archive)

    verify = subparsers.add_parser(
        "verify",
        help="verify archived files against a manifest",
    )
    verify.add_argument("--manifest", required=True, help="manifest.json to verify")
    add_json_arg(verify)
    verify.set_defaults(handler=handle_verify)

    prune = subparsers.add_parser(
        "prune-local",
        help="delete local session files only after archive verification passes",
    )
    prune.add_argument("--manifest", required=True, help="verified manifest.json")
    prune.add_argument(
        "--confirm-prune-local",
        action="store_true",
        help="required confirmation before deleting local session files",
    )
    prune.add_argument(
        "--allow-codex-running",
        action="store_true",
        help="override the Codex process check for local pruning",
    )
    add_json_arg(prune)
    prune.set_defaults(handler=handle_prune)

    return parser


def add_selection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--session-root",
        default=None,
        help="session root to scan (default: the --agent session root)",
    )
    parser.add_argument(
        "--agent",
        choices=AGENTS,
        default=None,
        help="which agent's sessions to archive: codex (~/.codex/sessions) or "
        "claude (~/.claude/projects); default: codex when present, else claude",
    )
    parser.add_argument(
        "--project",
        help="only include sessions whose recorded project path exactly matches this value",
    )
    parser.add_argument(
        "--older-than",
        help="only include sessions inactive longer than this duration, e.g. 30d, 12h, 90m",
    )
    parser.add_argument(
        "--min-size",
        default="0",
        help="only include files at or above this size, e.g. 100MiB, 1GiB, 500KB",
    )
    parser.add_argument(
        "--now",
        help="override the current UTC timestamp for deterministic planning",
    )


def add_json_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON",
    )


if __name__ == "__main__":
    sys.exit(main())
