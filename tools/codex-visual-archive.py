#!/usr/bin/env python3
"""Scan and archive visual references from Codex session JSONL files."""

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
from codex_thread_tools.visual_artifacts import (
    archive_visuals,
    scan_session_visuals,
    verify_manifest,
)


def json_or_pretty(payload: dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(payload, indent=2)
    if "artifacts" in payload and "summary" in payload:
        summary = payload["summary"]
        lines = [
            "Codex Visual Archive Scan",
            f"Source session: {payload.get('source_session', payload.get('archive_dir', ''))}",
            (
                "Visuals: "
                f"{summary.get('occurrences', 0)} occurrences, "
                f"{summary.get('embedded', 0)} embedded, "
                f"{summary.get('local_files', 0)} local, "
                f"{summary.get('videos', 0)} videos, "
                f"{summary.get('errors', 0)} errors, "
                f"{summary.get('skipped', 0)} skipped"
            ),
        ]
        for artifact in payload.get("artifacts", [])[:10]:
            lines.append(
                f"- {artifact['artifact_id']}: {artifact['status']} "
                f"{artifact['media_kind']} {artifact['source']['source_kind']} "
                f"line {artifact['source']['line_no']}"
            )
            if artifact.get("error"):
                lines.append(f"  {artifact['error']}")
        return "\n".join(lines)
    if payload.get("manifest_markdown"):
        return (
            "Codex Visual Archive Written\n"
            f"Manifest: {payload['manifest_markdown']}\n"
            f"JSON: {payload['manifest_json']}\n"
            f"Handoff snippet: {payload['handoff_snippet']}"
        )
    if "checked_files" in payload:
        return (
            "Codex Visual Archive Verify\n"
            f"Status: {payload['status'].upper()}\n"
            f"Checked files: {payload['checked_files']}\n"
            f"Missing files: {payload['missing_files']}"
        )
    return json.dumps(payload, indent=2)


def ensure_session_file(value: str) -> Path:
    path = expand_path(value)
    if not path.exists():
        die(f"session file does not exist: {path}")
    if not path.is_file():
        die(f"session path is not a file: {path}")
    return path


def allow_roots(args: argparse.Namespace) -> list[Path]:
    return [expand_path(value) for value in getattr(args, "allow_local_root", [])]


def scan_command(args: argparse.Namespace) -> int:
    session_file = ensure_session_file(args.session_file)
    result = scan_session_visuals(session_file, allow_roots(args))
    print(json_or_pretty(result, args.format))
    return 0


def archive_command(args: argparse.Namespace) -> int:
    session_file = ensure_session_file(args.session_file)
    result = archive_visuals(
        session_file=session_file,
        archive_root=expand_path(args.archive_root),
        project_name=args.project_name,
        artifact_set=args.artifact_set,
        visual_context=args.visual_context,
        allow_local_roots=allow_roots(args),
        force=args.force,
        dry_run=args.dry_run,
    )
    print(json_or_pretty(result, args.format))
    return 0


def verify_command(args: argparse.Namespace) -> int:
    manifest_path = expand_path(args.manifest)
    if not manifest_path.exists():
        die(f"manifest does not exist: {manifest_path}")
    result = verify_manifest(manifest_path)
    print(json_or_pretty(result, args.format))
    return 2 if result["status"] == "warn" else 0


def wizard_command(args: argparse.Namespace) -> int:
    session_file = ensure_session_file(args.session_file)
    scan = scan_session_visuals(session_file, allow_roots(args))
    print(json_or_pretty(scan, "pretty"))
    print("")
    archive_root = input("Archive location (external drive or folder): ").strip()
    project_name = input("Project name: ").strip() or "Codex project"
    artifact_set = input("Visual set name: ").strip() or "visual-references"
    visual_context = input("Short note describing these visuals: ").strip()
    extra_root = input("Allowed local visual folder (optional): ").strip()
    roots = allow_roots(args)
    if extra_root:
        roots.append(expand_path(extra_root))
    confirm = input("Copy visuals to the archive now? [y/N]: ").strip().lower()
    if confirm not in {"y", "yes"}:
        print("No archive written.")
        return 0
    if not archive_root:
        die("archive location is required when copying")
    result = archive_visuals(
        session_file=session_file,
        archive_root=expand_path(archive_root),
        project_name=project_name,
        artifact_set=artifact_set,
        visual_context=visual_context,
        allow_local_roots=roots,
        force=args.force,
    )
    print(json_or_pretty(result, args.format))
    return 0


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--allow-local-root", action="append", default=[])
    parser.add_argument("--format", choices=("json", "pretty"), default="pretty")
    parser.add_argument(
        "--json",
        action="store_const",
        const="json",
        dest="format",
        help="print machine-readable JSON",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archive image and video references from Codex session JSONL files."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="read-only visual artifact scan")
    scan.add_argument("session_file")
    add_common(scan)
    scan.set_defaults(func=scan_command)

    archive = subparsers.add_parser("archive", help="copy visual artifacts to archive storage")
    archive.add_argument("session_file")
    archive.add_argument("--archive-root", required=True)
    archive.add_argument("--project-name", required=True)
    archive.add_argument("--artifact-set", required=True)
    archive.add_argument("--visual-context", required=True)
    archive.add_argument("--force", action="store_true")
    archive.add_argument("--dry-run", action="store_true")
    add_common(archive)
    archive.set_defaults(func=archive_command)

    wizard = subparsers.add_parser("wizard", help="interactive archive setup")
    wizard.add_argument("session_file")
    wizard.add_argument("--force", action="store_true")
    add_common(wizard)
    wizard.set_defaults(func=wizard_command)

    verify = subparsers.add_parser("verify", help="verify archived manifest files still exist")
    verify.add_argument("manifest")
    verify.add_argument("--format", choices=("json", "pretty"), default="pretty")
    verify.add_argument("--json", action="store_const", const="json", dest="format")
    verify.set_defaults(func=verify_command)
    return parser


def main(argv: list[str] | None = None) -> int:
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
