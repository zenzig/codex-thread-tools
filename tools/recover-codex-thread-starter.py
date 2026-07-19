#!/usr/bin/env python3
"""
Starter recovery utility for oversized Codex session JSONL files.

This script is intentionally conservative:
- it refuses to run write operations while Codex appears to be open
- it creates a backup before replacing a live session file
- it writes repaired output to a separate file unless --replace-live is used
- it validates that essential records are preserved before writing

Typical flow:
  1. inspect          - understand the size and record mix
  2. backup           - preserve the raw session file
  3. strip-compacted  - remove huge compaction records
  4. rebuild-window   - optional last-resort rebuild from a recent real window
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codex_thread_tools.cli import add_common_args
from codex_thread_tools.atomic_directory import staged_directory
from codex_thread_tools.handoff_summary import (
    build_handoff_summary,
    format_handoff_summary,
    pre_handoff_safety,
)
from codex_thread_tools.sessionpaths import default_session_root
from codex_thread_tools.session_integrity import scan_session_integrity
from codex_thread_tools.sessionlib import (
    KEEP_EVENT_TYPES,
    die,
    expand_path,
    is_codex_running,
    iter_jsonl,
    now_iso,
    now_stamp,
    payload_role,
    payload_type,
    sha256_file,
    record_timestamp,
)
from codex_thread_tools.thread_health import HealthThresholds, analyze_session_file


def require_codex_closed(allow_running: bool) -> None:
    if allow_running:
        die("--allow-codex-running is only supported by the read-only inspect command")
    if is_codex_running():
        die(
            "Codex appears to be running. Quit Codex completely, then rerun. "
            "Use --allow-codex-running only with the read-only inspect command."
        )


def ensure_source(path: Path) -> None:
    if not path.exists():
        die(f"session file does not exist: {path}")
    if not path.is_file():
        die(f"session path is not a file: {path}")


def backup_session(source: Path, backup_dir: Path) -> Path:
    ensure_source(source)
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"{source.stem}.raw-{now_stamp()}{source.suffix}"

    try:
        os.link(source, destination)
        method = "hard link"
    except OSError:
        shutil.copy2(source, destination)
        method = "copy"

    print(f"backup: {destination}")
    print(f"method: {method}")
    print(f"source_bytes: {source.stat().st_size}")
    print(f"backup_bytes: {destination.stat().st_size}")
    return destination


def open_output_path(path: Path, force: bool) -> Path:
    if path.exists() and not force:
        die(f"output file already exists: {path} (use --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def is_within_directory(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
    except ValueError:
        return False
    return True


def require_live_replace_confirmation(source: Path, confirmation: str | None) -> None:
    expected = str(source)
    if confirmation != expected:
        die(
            "--replace-live modifies the source session file. To proceed, rerun with "
            f"--confirm-replace-live {expected!r}"
        )


def require_not_live_session_output(target: Path) -> None:
    session_root = default_session_root()
    if is_within_directory(target, session_root):
        die(
            "refusing to write repair output under ~/.codex/sessions. Write to a "
            "scratch path outside the live Codex session tree, then inspect it before "
            "using --replace-live with --confirm-replace-live."
        )


def prepare_write_target(
    source: Path,
    output: str | None,
    replace_live: bool,
    backup_dir: Path,
    force: bool,
    confirm_replace_live: str | None,
) -> tuple[Path, Path | None]:
    if replace_live:
        require_live_replace_confirmation(source, confirm_replace_live)
        backup_session(source, backup_dir)
        temp = source.with_name(f"{source.name}.repair-{now_stamp()}.tmp")
        if temp.exists():
            die(f"temporary repair file already exists: {temp}")
        return temp, source

    if not output:
        die("provide --output, or use --replace-live after making a backup")

    target = expand_path(output)
    if target == source:
        die("refusing to write directly over the source without --replace-live")
    require_not_live_session_output(target)
    target = open_output_path(target, force)
    return target, None


def replace_if_requested(temp: Path, live: Path | None) -> None:
    if live is None:
        print(f"written: {temp}")
        return

    temp.replace(live)
    print(f"replaced_live: {live}")


def inspect_session(args: argparse.Namespace) -> None:
    source = expand_path(args.session_file)
    ensure_source(source)

    summary: dict[str, Any] = {
        "file": str(source),
        "bytes": source.stat().st_size,
        "total_records": 0,
        "session_meta_records": 0,
        "turn_context_records": 0,
        "compacted_records": 0,
        "response_items": 0,
        "response_messages": 0,
        "event_messages": 0,
        "user_message_events": 0,
        "agent_message_events": 0,
        "first_timestamp": "",
        "last_timestamp": "",
        "largest_lines": [],
    }

    largest: list[dict[str, Any]] = []
    for line_no, raw, record in iter_jsonl(source):
        summary["total_records"] += 1
        record_type = record.get("type")
        ptype = payload_type(record)
        ts = record_timestamp(record)

        if ts and not summary["first_timestamp"]:
            summary["first_timestamp"] = ts
        if ts:
            summary["last_timestamp"] = ts

        if record_type == "session_meta":
            summary["session_meta_records"] += 1
        elif record_type == "turn_context":
            summary["turn_context_records"] += 1
        elif record_type == "compacted":
            summary["compacted_records"] += 1
        elif record_type == "response_item":
            summary["response_items"] += 1
            if ptype == "message":
                summary["response_messages"] += 1
        elif record_type == "event_msg":
            summary["event_messages"] += 1
            if ptype == "user_message":
                summary["user_message_events"] += 1
            elif ptype == "agent_message":
                summary["agent_message_events"] += 1

        largest.append(
            {
                "line": line_no,
                "bytes": len(raw),
                "type": record_type,
                "payload_type": ptype,
                "timestamp": ts,
            }
        )
        largest.sort(key=lambda item: item["bytes"], reverse=True)
        del largest[args.largest_lines :]

    summary["largest_lines"] = largest
    print(json.dumps(summary, indent=2))


def diagnose_session(args: argparse.Namespace) -> int:
    source = expand_path(args.session_file)
    ensure_source(source)
    diagnosis = collect_diagnosis(source, max_findings=args.max_findings)

    if args.json:
        print(json.dumps(diagnosis, indent=2, sort_keys=True))
    else:
        print(format_diagnosis(diagnosis))
    return diagnosis_exit_code(diagnosis["status"])


def format_diagnosis(diagnosis: dict[str, Any]) -> str:
    safety = diagnosis["pre_handoff_safety"]
    integrity = diagnosis["integrity"]
    lines = [
        "Codex Session Integrity Diagnosis",
        f"File: {diagnosis['file']}",
        f"Project: {diagnosis['project'] or 'not recorded'}",
        f"Session: {diagnosis['session_id'] or 'not recorded'}",
        f"Status: {diagnosis['status'].upper()}",
        f"Pre-handoff safety: {safety['status'].upper()}",
        "",
        "Integrity",
        f"Invalid image URLs: {integrity['invalid_image_urls']}",
        "Invalid image URLs in compacted history: "
        f"{integrity['invalid_image_urls_in_compacted_records']}",
        f"Remote image URLs: {integrity['remote_image_urls']}",
        f"History base present: {'yes' if integrity['history_base_present'] else 'no'}",
    ]
    if integrity["findings"]:
        lines.append("Findings")
        for finding in integrity["findings"]:
            location = "compacted history" if finding["compacted"] else "live history"
            lines.append(
                f"- {finding['code']} at line {finding['line']} ({location})"
            )
    if safety["reasons"]:
        lines.append("Pre-handoff notes")
        for reason in safety["reasons"]:
            lines.append(f"- {reason}")
    lines.extend(
        [
            "",
            f"Recommended action: {diagnosis['recommended_action']}",
        ]
    )
    return "\n".join(lines)


def diagnosis_exit_code(status: str) -> int:
    if status == "clean":
        return 0
    if status == "caution":
        return 2
    if status == "danger":
        return 3
    return 1


def collect_diagnosis(source: Path, *, max_findings: int = 20) -> dict[str, Any]:
    diagnosis, _health = collect_diagnosis_with_health(
        source,
        max_findings=max_findings,
    )
    return diagnosis


def collect_diagnosis_with_health(
    source: Path,
    *,
    max_findings: int = 20,
) -> tuple[dict[str, Any], dict[str, Any]]:
    health = analyze_session_file(source, HealthThresholds())
    integrity = scan_session_integrity(source, max_findings=max_findings)
    safety = pre_handoff_safety(health["metrics"], health)

    if integrity.invalid_image_urls or integrity.remote_image_urls:
        status = "danger"
        recommended_action = "create-recovery-bundle"
    elif safety["status"] != "clean" or health["status"] != "ok":
        status = "caution"
        recommended_action = "review-before-handoff"
    else:
        status = "clean"
        recommended_action = "continue"

    diagnosis = {
        "report_type": "codex_session_integrity_diagnosis",
        "file": str(source),
        "project": health["project"],
        "session_id": health["session_id"],
        "status": status,
        "recommended_action": recommended_action,
        "pre_handoff_safety": safety,
        "integrity": {
            "invalid_image_urls": integrity.invalid_image_urls,
            "invalid_image_urls_in_compacted_records": (
                integrity.invalid_image_urls_in_compacted_records
            ),
            "remote_image_urls": integrity.remote_image_urls,
            "remote_image_urls_in_compacted_records": (
                integrity.remote_image_urls_in_compacted_records
            ),
            "history_base_present": integrity.history_base_present,
            "findings": [asdict(finding) for finding in integrity.findings],
        },
    }
    return diagnosis, health


def collect_source_identity(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "file": str(path),
        "path": str(path),
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def ensure_source_unchanged(path: Path, expected: dict[str, Any]) -> None:
    current = collect_source_identity(path)
    for key in ("file", "device", "inode", "size", "mtime_ns", "sha256"):
        if current[key] != expected[key]:
            die("session source changed during bundle creation")


def capture_directory_identity(path: Path) -> tuple[int, int]:
    if path.is_symlink():
        die(f"bundle output root is a symlink: {path}")
    if not path.exists():
        path.mkdir(parents=True)
    if not path.is_dir():
        die(f"bundle output root is not a directory: {path}")
    stat = path.stat()
    return stat.st_dev, stat.st_ino


def ensure_bundle_output_root(
    path: Path,
    expected_identity: tuple[int, int],
) -> None:
    require_not_live_session_output(path)
    if path.is_symlink():
        die(f"bundle output root is a symlink: {path}")
    if not path.is_dir():
        die(f"bundle output root is not a directory: {path}")
    stat = path.stat()
    if (stat.st_dev, stat.st_ino) != expected_identity:
        die("bundle output root changed during bundle creation")


def _guard_context_text(value: str) -> str:
    if "data:image/" in value.lower():
        return "[redacted image data URL]"
    if len(value) > 500:
        return value[:500].rstrip() + "..."
    return value


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_bundle_manifest(
    staging_dir: Path,
    bundle_dir: Path,
) -> dict[str, Any]:
    artifacts = {
        "integrity-report.json": {
            "path": str(bundle_dir / "integrity-report.json"),
            "sha256": sha256_file(staging_dir / "integrity-report.json"),
            "bytes": (staging_dir / "integrity-report.json").stat().st_size,
        },
        "recovery.md": {
            "path": str(bundle_dir / "recovery.md"),
            "sha256": sha256_file(staging_dir / "recovery.md"),
            "bytes": (staging_dir / "recovery.md").stat().st_size,
        },
        "handoff-template.md": {
            "path": str(bundle_dir / "handoff-template.md"),
            "sha256": sha256_file(staging_dir / "handoff-template.md"),
            "bytes": (staging_dir / "handoff-template.md").stat().st_size,
        },
        "fresh-task-prompt.md": {
            "path": str(bundle_dir / "fresh-task-prompt.md"),
            "sha256": sha256_file(staging_dir / "fresh-task-prompt.md"),
            "bytes": (staging_dir / "fresh-task-prompt.md").stat().st_size,
        },
        "visual-decision.md": {
            "path": str(bundle_dir / "visual-decision.md"),
            "sha256": sha256_file(staging_dir / "visual-decision.md"),
            "bytes": (staging_dir / "visual-decision.md").stat().st_size,
        },
    }
    return {
        "type": "codex_session_recovery_bundle",
        "version": 1,
        "created_at": now_iso(),
        "files": list(artifacts.keys()),
        "artifacts": artifacts,
    }


def run_bundle(args: argparse.Namespace) -> int:
    source = expand_path(args.session_file)
    ensure_source(source)
    project_root = expand_path(args.project_root)
    if not project_root.exists():
        die(f"project root does not exist: {project_root}")
    if not project_root.is_dir():
        die(f"project root is not a directory: {project_root}")

    output_root = expand_path(
        args.output_root or "~/.codex/thread-tools/recovery-bundles"
    )
    require_not_live_session_output(output_root)
    output_root_identity = capture_directory_identity(output_root)

    source_identity = collect_source_identity(source)
    bundle_dir = output_root / f"{source.stem}-{now_stamp()}"

    def before_stage() -> None:
        ensure_bundle_output_root(output_root, output_root_identity)

    def before_publish() -> None:
        ensure_bundle_output_root(output_root, output_root_identity)
        ensure_source_unchanged(source, source_identity)

    with staged_directory(
        bundle_dir,
        replace=args.force,
        before_stage=before_stage,
        before_publish=before_publish,
    ) as staging_dir:
        diagnosis, health = collect_diagnosis_with_health(source)
        handoff = build_handoff_summary(source, health=health)
        for item in handoff["durable_context"]:
            item["text"] = _guard_context_text(item["text"])

        integrity_report = {
            "report_type": "codex_session_recovery_bundle_report",
            "source": source_identity,
            "project_root": str(project_root),
            "diagnosis": {
                "status": diagnosis["status"],
                "recommended_action": diagnosis["recommended_action"],
                "pre_handoff_safety": diagnosis["pre_handoff_safety"],
            },
            "integrity": diagnosis["integrity"],
        }
        _write_json(staging_dir / "integrity-report.json", integrity_report)

        _write_text(
            staging_dir / "recovery.md",
            "\n".join(
                [
                    "# Recovery Bundle",
                    "",
                    f"Session: `{diagnosis['file']}`",
                    f"Project root: `{project_root}`",
                    f"Status: `{diagnosis['status'].upper()}`",
                    "",
                    "Evidence",
                    f"- Invalid image URLs: {diagnosis['integrity']['invalid_image_urls']}",
                    f"- Remote image URLs: {diagnosis['integrity']['remote_image_urls']}",
                    f"- History base declared: {'yes' if diagnosis['integrity']['history_base_present'] else 'no'}",
                    "",
                    "Decision",
                    "- Create a fresh task instead of resuming or forking this session.",
                ]
            )
            + "\n",
        )

        handoff_lines = format_handoff_summary(handoff).splitlines()
        _write_text(
            staging_dir / "handoff-template.md",
            "\n".join(
                [
                    "# Recovery Handoff Template",
                    "",
                    "- Keep this task fresh. Do not resume the prior transcript.",
                    "",
                ]
                + handoff_lines
                + [
                    "",
                    "Checklist",
                    "- [ ] Verify git status and working tree diffs",
                    "- [ ] Review the last few commits",
                    "- [ ] Confirm whether visual artifacts are needed",
                    "- [ ] Continue in a new task with the redacted summary only",
                ]
            )
            + "\n",
        )
        _write_text(
            staging_dir / "fresh-task-prompt.md",
            "\n".join(
                [
                    "Start a new Codex task from this redacted summary.",
                    "",
                    "Do not resume, fork, or trust the broken live transcript. "
                    "Use this bundle to bootstrap context, then continue from a clean state.",
                    "",
                    f"Source session: `{source}`",
                    f"Bundle: `{bundle_dir}`",
                ]
            )
            + "\n",
        )
        _write_text(
            staging_dir / "visual-decision.md",
            "\n".join(
                [
                    "# Visual Decision",
                    "",
                    "Recommended visual action: `Not archived`",
                    "Decision: if visual context is necessary, run visual-archive scan before new handoff.",
                ]
            )
            + "\n",
        )

        manifest = build_bundle_manifest(staging_dir, bundle_dir)
        manifest["project_root"] = str(project_root)
        manifest["source"] = source_identity
        manifest["files"] = [
            "integrity-report.json",
            "recovery.md",
            "handoff-template.md",
            "fresh-task-prompt.md",
            "visual-decision.md",
            "manifest.json",
        ]
        _write_json(staging_dir / "manifest.json", manifest)

    print(f"bundle: {bundle_dir}")
    return 0


def backup_command(args: argparse.Namespace) -> None:
    require_codex_closed(args.allow_codex_running)
    source = expand_path(args.session_file)
    backup_session(source, expand_path(args.backup_dir))


def strip_compacted(args: argparse.Namespace) -> None:
    require_codex_closed(args.allow_codex_running)
    source = expand_path(args.session_file)
    ensure_source(source)
    target, live = prepare_write_target(
        source,
        args.output,
        args.replace_live,
        expand_path(args.backup_dir),
        args.force,
        args.confirm_replace_live,
    )

    total = kept = skipped = 0
    session_meta_seen = False
    with target.open("wb") as dst:
        for _line_no, raw, record in iter_jsonl(source):
            total += 1
            if record.get("type") == "compacted":
                skipped += 1
                continue
            if record.get("type") == "session_meta":
                session_meta_seen = True
            dst.write(raw)
            kept += 1

    if not session_meta_seen:
        target.unlink(missing_ok=True)
        die("no session_meta record was preserved; repair output removed")
    if skipped == 0:
        target.unlink(missing_ok=True)
        die("no compacted records found; repair output removed")
    if target.stat().st_size >= source.stat().st_size:
        target.unlink(missing_ok=True)
        die("repair output is not smaller than source; repair output removed")

    replace_if_requested(target, live)
    print(f"records_total: {total}")
    print(f"records_kept: {kept}")
    print(f"compacted_removed: {skipped}")


def in_window(timestamp: str, start: str, end: str) -> bool:
    return bool(timestamp) and start <= timestamp <= end


def make_resume_records(resume_text: str) -> list[dict[str, Any]]:
    ts = now_iso()
    response_item = {
        "timestamp": ts,
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": resume_text}],
        },
    }
    event_msg = {
        "timestamp": ts,
        "type": "event_msg",
        "payload": {
            "type": "user_message",
            "message": resume_text,
            "images": [],
            "local_images": [],
            "text_elements": [],
        },
    }
    return [response_item, event_msg]


def rebuild_window(args: argparse.Namespace) -> None:
    require_codex_closed(args.allow_codex_running)
    source = expand_path(args.session_file)
    ensure_source(source)
    target, live = prepare_write_target(
        source,
        args.output,
        args.replace_live,
        expand_path(args.backup_dir),
        args.force,
        args.confirm_replace_live,
    )

    session_meta: dict[str, Any] | None = None
    chosen_turn_context: dict[str, Any] | None = None
    fallback_turn_context: dict[str, Any] | None = None
    selected: list[dict[str, Any]] = []
    message_records = 0
    event_records = 0

    for _line_no, _raw, record in iter_jsonl(source):
        rtype = record.get("type")
        ptype = payload_type(record)
        ts = record_timestamp(record)

        if session_meta is None and rtype == "session_meta":
            session_meta = record

        if rtype == "turn_context":
            if ts <= args.end:
                fallback_turn_context = record
            if in_window(ts, args.start, args.end):
                chosen_turn_context = record
            continue

        if not in_window(ts, args.start, args.end):
            continue

        if rtype == "event_msg" and ptype in KEEP_EVENT_TYPES:
            selected.append(record)
            event_records += 1
        elif rtype == "response_item" and ptype == "message":
            role = payload_role(record)
            if role in {"user", "assistant"}:
                selected.append(record)
                message_records += 1

    turn_context = chosen_turn_context or fallback_turn_context
    if session_meta is None:
        target.unlink(missing_ok=True)
        die("no session_meta found; repair output removed")
    if turn_context is None:
        target.unlink(missing_ok=True)
        die("no turn_context found before or inside the requested window")
    if message_records < 2 and not args.allow_small_window:
        target.unlink(missing_ok=True)
        die(
            "fewer than two user/assistant message records found in the window; "
            "expand --start/--end or use --allow-small-window"
        )
    if event_records == 0 and not args.allow_small_window:
        target.unlink(missing_ok=True)
        die(
            "no sidebar event_msg records found in the window; expand the window "
            "or use --allow-small-window"
        )

    output_records = [session_meta, turn_context] + selected + make_resume_records(args.resume_text)
    with target.open("w", encoding="utf-8") as handle:
        for record in output_records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    replace_if_requested(target, live)
    print(f"records_written: {len(output_records)}")
    print(f"message_records_kept: {message_records}")
    print(f"event_records_kept: {event_records}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and repair oversized Codex session JSONL files."
    )
    add_common_args(parser, allow_codex_running=True)

    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="summarize a session file")
    inspect_parser.add_argument("session_file")
    inspect_parser.add_argument("--largest-lines", type=int, default=8)
    inspect_parser.set_defaults(func=inspect_session)

    diagnose_parser = subparsers.add_parser(
        "diagnose",
        help="read-only integrity diagnosis for a session file",
        description="Read-only integrity diagnosis for a Codex session file.",
    )
    diagnose_parser.add_argument("session_file")
    diagnose_parser.add_argument("--json", action="store_true")
    diagnose_parser.add_argument("--max-findings", type=int, default=20)
    diagnose_parser.set_defaults(func=diagnose_session)

    backup_parser = subparsers.add_parser("backup", help="hard-link or copy a session backup")
    backup_parser.add_argument("session_file")
    add_common_args(backup_parser, backup_dir=True)
    backup_parser.set_defaults(func=backup_command)

    strip_parser = subparsers.add_parser(
        "strip-compacted", help="write a copy with compacted records removed"
    )
    strip_parser.add_argument("session_file")
    strip_parser.add_argument("--output")
    strip_parser.add_argument("--replace-live", action="store_true")
    strip_parser.add_argument(
        "--confirm-replace-live",
        help="exact resolved session path required with --replace-live",
    )
    add_common_args(strip_parser, backup_dir=True, force=True)
    strip_parser.set_defaults(func=strip_compacted)

    rebuild_parser = subparsers.add_parser(
        "rebuild-window", help="rebuild a small live thread from a recent time window"
    )
    rebuild_parser.add_argument("session_file")
    rebuild_parser.add_argument("--start", required=True, help="ISO timestamp window start")
    rebuild_parser.add_argument("--end", required=True, help="ISO timestamp window end")
    rebuild_parser.add_argument("--output")
    rebuild_parser.add_argument("--replace-live", action="store_true")
    rebuild_parser.add_argument(
        "--confirm-replace-live",
        help="exact resolved session path required with --replace-live",
    )
    add_common_args(rebuild_parser, backup_dir=True, force=True)
    rebuild_parser.add_argument(
        "--resume-text",
        default=(
            "Continue from this recovered handoff. Read the repo, inspect git status, "
            "and proceed with the next task."
        ),
    )
    rebuild_parser.add_argument("--allow-small-window", action="store_true")
    rebuild_parser.set_defaults(func=rebuild_window)

    bundle_parser = subparsers.add_parser(
        "bundle",
        help="write a recovery bundle for source integrity remediation",
    )
    bundle_parser.add_argument("session_file")
    bundle_parser.add_argument("--project-root", required=True)
    bundle_parser.add_argument(
        "--output-root",
        default="~/.codex/thread-tools/recovery-bundles",
    )
    bundle_parser.add_argument("--force", action="store_true")
    bundle_parser.set_defaults(func=run_bundle)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = args.func(args)
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
