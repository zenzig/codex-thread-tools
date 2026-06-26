#!/usr/bin/env python3
"""Archive Codex session JSONL files to external storage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codex_thread_tools.session_archive import (
    archive_sessions,
    build_archive_plan,
    format_archive,
    format_plan,
    format_prune,
    format_verify,
    prune_local_sessions,
    verify_archive,
)
from codex_thread_tools.sessionlib import expand_path, is_codex_running
from codex_thread_tools.sessionpaths import default_session_root


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.handler(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def handle_plan(args: argparse.Namespace) -> int:
    result = build_archive_plan(
        session_root=expand_path(args.session_root),
        project=args.project,
        older_than=args.older_than,
        min_size=args.min_size,
        now=args.now,
    )
    emit(result, args.json, format_plan)
    return 0


def handle_archive(args: argparse.Namespace) -> int:
    result = archive_sessions(
        session_root=expand_path(args.session_root),
        archive_root=expand_path(args.archive_root),
        project=args.project,
        older_than=args.older_than,
        min_size=args.min_size,
        archive_name=args.archive_name,
        now=args.now,
        force=args.force,
    )
    emit(result, args.json, format_archive)
    return 0


def handle_verify(args: argparse.Namespace) -> int:
    result = verify_archive(expand_path(args.manifest))
    emit(result, args.json, format_verify)
    return 3 if result["summary"]["failed"] else 0


def handle_prune(args: argparse.Namespace) -> int:
    if is_codex_running() and not args.allow_codex_running:
        print(
            "error: Codex appears to be running. Quit Codex before pruning local "
            "session files, or pass --allow-codex-running if you have verified "
            "this is safe.",
            file=sys.stderr,
        )
        return 1
    result = prune_local_sessions(
        manifest_file=expand_path(args.manifest),
        confirm_prune_local=args.confirm_prune_local,
    )
    emit(result, args.json, format_prune)
    return 0


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
        description="Archive old Codex session JSONL files to external storage."
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
        help="external archive root outside ~/.codex/sessions",
    )
    archive.add_argument(
        "--archive-name",
        help="archive folder name under codex-session-archives",
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
        default=str(default_session_root()),
        help="Codex session root to scan",
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
