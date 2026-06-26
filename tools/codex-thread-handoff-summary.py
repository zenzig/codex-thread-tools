#!/usr/bin/env python3
"""Generate a redacted Codex thread handoff summary draft."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codex_thread_tools.handoff_summary import build_handoff_summary, format_handoff_summary
from codex_thread_tools.sessionlib import die, expand_path
from codex_thread_tools.thread_health import (
    HealthThresholds,
    assert_safe_test_root,
    exit_code_for_status,
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


def ensure_file(path: Path) -> None:
    if not path.exists():
        die(f"session file does not exist: {path}")
    if not path.is_file():
        die(f"session path is not a file: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    source = expand_path(args.session_file)
    if args.safe_test_mode:
        assert_safe_test_root(source)
    ensure_file(source)

    summary = build_handoff_summary(
        source,
        thresholds=apply_threshold_overrides(args),
        max_items=args.max_items,
        max_text_chars=args.max_text_chars,
    )
    if args.format == "json":
        print(json.dumps(summary, indent=2))
    else:
        print(format_handoff_summary(summary))
    return exit_code_for_status(summary["health"]["status"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a redacted handoff summary draft from one Codex session JSONL file."
    )
    parser.add_argument("session_file")
    parser.add_argument("--warn-bytes", type=int)
    parser.add_argument("--danger-bytes", type=int)
    parser.add_argument("--warn-items", type=int)
    parser.add_argument("--danger-items", type=int)
    parser.add_argument("--max-healthy-compactions", type=int)
    parser.add_argument(
        "--max-items",
        type=int,
        default=8,
        help="maximum durable context items to include",
    )
    parser.add_argument(
        "--max-text-chars",
        type=int,
        default=500,
        help="maximum characters per durable context item",
    )
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
        help="print machine-readable JSON instead of the human summary",
    )
    return parser


if __name__ == "__main__":
    sys.exit(main())
