#!/usr/bin/env python3
"""Record local sidecar markers for completed Codex thread handoffs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codex_thread_tools.handoff_markers import (
    append_handoff_marker,
    default_marker_file,
    marker_prompt_block,
    session_identity,
)
from codex_thread_tools.sessionlib import die, expand_path


def record_command(args: argparse.Namespace) -> int:
    marker_file = expand_path(args.marker_file)
    source_session_file = expand_path(args.source_session_file)
    handoff_file = expand_path(args.handoff_file)
    if not source_session_file.exists():
        die(f"source session file does not exist: {source_session_file}")
    identity = session_identity(source_session_file)
    project = args.project or identity["project"]
    source_session_id = args.source_session_id or identity["session_id"]
    if not project:
        die("project could not be determined; pass --project")
    if not source_session_id:
        die("source session id could not be determined; pass --source-session-id")
    replacement_session_file = ""
    replacement_session_id = args.replacement_session_id or ""
    if args.replacement_session_file:
        replacement_path = expand_path(args.replacement_session_file)
        if not replacement_path.exists():
            die(f"replacement session file does not exist: {replacement_path}")
        replacement_identity = session_identity(replacement_path)
        replacement_session_file = str(replacement_path)
        replacement_session_id = replacement_session_id or replacement_identity["session_id"]

    marker = append_handoff_marker(
        marker_file,
        project=project,
        source_session_id=source_session_id,
        source_session_file=str(source_session_file),
        replacement_session_id=replacement_session_id,
        replacement_session_file=replacement_session_file,
        handoff_file=str(handoff_file),
        created_at=args.created_at,
    )
    if args.format == "json":
        print(json.dumps({"marker_file": str(marker_file), "marker": marker}, indent=2))
    else:
        print(f"Marker file: {marker_file}")
        print(marker_prompt_block(marker))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record completed Codex thread handoffs in a local sidecar file."
    )
    subparsers = parser.add_subparsers(dest="command")

    record = subparsers.add_parser("record", help="append a handoff completion marker")
    record.add_argument(
        "--marker-file",
        default=str(default_marker_file()),
        help="local marker JSONL file to append",
    )
    record.add_argument("--project", help="project path; defaults from source session")
    record.add_argument("--source-session-id", help="source session id; defaults from source session")
    record.add_argument("--source-session-file", required=True)
    record.add_argument(
        "--replacement-session-id",
        help="replacement session id; defaults from replacement session",
    )
    record.add_argument(
        "--replacement-session-file",
        help="replacement session file for older handoffs without a prompt marker",
    )
    record.add_argument("--handoff-file", required=True)
    record.add_argument("--created-at", help="ISO timestamp; defaults to current UTC time")
    record.add_argument("--format", choices=("pretty", "json"), default="pretty")
    record.add_argument(
        "--json",
        action="store_const",
        const="json",
        dest="format",
        help="print machine-readable JSON",
    )
    record.set_defaults(func=record_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except SystemExit as exc:
        if isinstance(exc.code, str) and exc.code.startswith("error:"):
            print(exc.code, file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
