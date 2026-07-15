from __future__ import annotations

import json
import os
import pytest
import subprocess
import sys
import importlib.util
from pathlib import Path
import time

from codex_thread_tools.atomic_directory import (
    _remove_path,
    _reservation_path,
    staged_directory,
)
from codex_thread_tools import atomic_directory
from codex_thread_tools import session_archive


ROOT = Path(__file__).resolve().parents[1]


def run_archive(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "codex-session-archive.py"), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_session(path: Path, *, project: str, session_id: str, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "type": "session_meta",
            "payload": {"id": session_id, "cwd": project},
        },
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": payload}],
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records)
        + "\n",
        encoding="utf-8",
    )


def test_plan_selects_project_sessions_by_age_and_size(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    project = "/work/atomic"
    large_old = session_root / "2026" / "01" / "01" / "large-old.jsonl"
    small_old = session_root / "2026" / "01" / "01" / "small-old.jsonl"
    other_project = session_root / "2026" / "01" / "01" / "other.jsonl"
    write_session(large_old, project=project, session_id="large-old", payload="x" * 4096)
    write_session(small_old, project=project, session_id="small-old", payload="small")
    write_session(other_project, project="/work/other", session_id="other", payload="x" * 4096)

    result = run_archive(
        "plan",
        "--session-root",
        str(session_root),
        "--project",
        project,
        "--older-than",
        "30d",
        "--min-size",
        "1KiB",
        "--now",
        "2026-06-26T00:00:00Z",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"]["candidate_count"] == 1
    assert payload["summary"]["total_bytes"] == large_old.stat().st_size
    assert payload["candidates"][0]["source_file"] == str(large_old.resolve())
    assert payload["candidates"][0]["session_id"] == "large-old"
    assert payload["candidates"][0]["project"] == project
    assert payload["candidates"][0]["size_bytes"] == large_old.stat().st_size


def test_plan_requires_existing_session_root(tmp_path: Path) -> None:
    result = run_archive(
        "plan",
        "--session-root",
        str(tmp_path / "missing"),
        "--json",
    )

    assert result.returncode == 1
    assert "session root does not exist" in result.stderr


def test_archive_copies_sessions_and_writes_verifiable_manifest(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project=project, session_id="thread-1", payload="archive me")

    result = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        project,
        "--older-than",
        "1d",
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--now",
        "2026-06-26T00:00:00Z",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    manifest_path = Path(payload["manifest_file"])
    archived_file = Path(payload["sessions"][0]["archive_file"])
    assert manifest_path.exists()
    assert archived_file.exists()
    assert archived_file.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert payload["summary"]["archived_count"] == 1
    assert payload["sessions"][0]["sha256"]

    verify = run_archive("verify", "--manifest", str(manifest_path), "--json")

    assert verify.returncode == 0, verify.stderr
    verify_payload = json.loads(verify.stdout)
    assert verify_payload["summary"]["ok"] == 1
    assert verify_payload["summary"]["failed"] == 0


def test_archive_sessions_verifies_staged_copy_contents_and_preserves_prior_archive_on_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project=project, session_id="thread-1", payload="x" * 2048)

    created = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        project,
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--json",
    )
    assert created.returncode == 0, created.stderr
    payload = json.loads(created.stdout)
    archived_file = Path(payload["sessions"][0]["archive_file"])
    original_archive_bytes = archived_file.read_bytes()

    original_copy2 = session_archive.shutil.copy2

    def mutate_staged_copy(source: Path, destination: Path) -> None:
        original_copy2(source, destination)
        destination.write_bytes(destination.read_bytes() + b"mutated")

    monkeypatch.setattr(session_archive.shutil, "copy2", mutate_staged_copy)

    with pytest.raises(RuntimeError, match="session .*changed"):
        session_archive.archive_sessions(
            session_root=session_root,
            archive_root=archive_root,
            project=project,
            older_than=None,
            min_size=None,
            archive_name="atomic-test",
            now=None,
            force=True,
        )

    assert archived_file.read_bytes() == original_archive_bytes
    assert not _generated_siblings(archive_root / "codex-session-archives")


def test_archive_sessions_rejects_source_change_after_planning(tmp_path: Path, monkeypatch) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project=project, session_id="thread-1", payload="x" * 2048)

    original_plan = session_archive.build_archive_plan(
        session_root=session_root,
        project=project,
        older_than=None,
        min_size=None,
        now=None,
    )

    def plan_then_mutate(*args, **kwargs):
        source.write_text("mutated before copy", encoding="utf-8")
        return original_plan

    monkeypatch.setattr(session_archive, "build_archive_plan", plan_then_mutate)

    with pytest.raises(RuntimeError, match="session .*changed"):
        session_archive.archive_sessions(
            session_root=session_root,
            archive_root=archive_root,
            project=project,
            older_than=None,
            min_size=None,
            archive_name=None,
            now=None,
            force=False,
        )


def test_archive_sessions_rejects_atomic_source_replacement_after_planning(tmp_path: Path, monkeypatch) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project=project, session_id="thread-1", payload="same-content")

    original_plan = session_archive.build_archive_plan(
        session_root=session_root,
        project=project,
        older_than=None,
        min_size=None,
        now=None,
    )
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_text("same-content", encoding="utf-8")

    def plan_then_replace(*args, **kwargs):
        replacement.replace(source)
        return original_plan

    monkeypatch.setattr(session_archive, "build_archive_plan", plan_then_replace)

    with pytest.raises(RuntimeError, match="source identity changed"):
        session_archive.archive_sessions(
            session_root=session_root,
            archive_root=archive_root,
            project=project,
            older_than=None,
            min_size=None,
            archive_name=None,
            now=None,
            force=False,
        )


def test_archive_sessions_detects_source_mutation_during_copy_and_preserves_prior_archive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project=project, session_id="thread-1", payload="x" * 2048)

    created = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        project,
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--json",
    )
    assert created.returncode == 0, created.stderr
    payload = json.loads(created.stdout)
    archived_file = Path(payload["sessions"][0]["archive_file"])
    original_archive_bytes = archived_file.read_bytes()

    original_copy2 = session_archive.shutil.copy2

    def copy_and_mutate_source(source_path: Path, destination: Path) -> None:
        original_copy2(source_path, destination)
        source_path.write_text("source-mutated\n", encoding="utf-8")

    monkeypatch.setattr(session_archive.shutil, "copy2", copy_and_mutate_source)

    with pytest.raises(RuntimeError, match="session .*changed"):
        session_archive.archive_sessions(
            session_root=session_root,
            archive_root=archive_root,
            project=project,
            older_than=None,
            min_size=None,
            archive_name="atomic-test",
            now=None,
            force=True,
        )

    assert source.read_text(encoding="utf-8") == "source-mutated\n"
    assert archived_file.read_bytes() == original_archive_bytes
    assert not _generated_siblings(archive_root / "codex-session-archives")


def test_archive_sessions_rejects_same_size_source_change_during_copy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project="/work/atomic", session_id="thread-1", payload="AAAA")
    original_copy = session_archive.shutil.copy2

    def copy_then_rewrite(source_path: Path, destination: Path) -> None:
        original_copy(source_path, destination)
        content = source_path.read_text(encoding="utf-8")
        rewritten = content.replace("AAAA", "BBBB")
        source_path.write_text(rewritten, encoding="utf-8")
        destination.write_text(rewritten, encoding="utf-8")

    monkeypatch.setattr(session_archive.shutil, "copy2", copy_then_rewrite)

    with pytest.raises(RuntimeError, match="source metadata changed"):
        session_archive.archive_sessions(
            session_root=session_root,
            archive_root=archive_root,
            project="/work/atomic",
            older_than=None,
            min_size=None,
            archive_name="atomic-test",
        )


def test_verify_reports_missing_or_tampered_archive_file(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project="/work/atomic", session_id="thread-1", payload="archive me")
    created = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        "/work/atomic",
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--json",
    )
    manifest_path = Path(json.loads(created.stdout)["manifest_file"])
    archived_file = Path(json.loads(created.stdout)["sessions"][0]["archive_file"])
    archived_file.write_text("tampered\n", encoding="utf-8")

    verify = run_archive("verify", "--manifest", str(manifest_path), "--json")

    assert verify.returncode == 3
    payload = json.loads(verify.stdout)
    assert payload["summary"]["ok"] == 0
    assert payload["summary"]["failed"] == 1
    assert payload["sessions"][0]["status"] == "failed"
    assert "sha256 mismatch" in payload["sessions"][0]["errors"]


def test_verify_uses_archive_relative_path_not_archive_file(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project="/work/atomic", session_id="thread-1", payload="archive me")
    created = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        "/work/atomic",
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--json",
    )
    manifest_path = Path(json.loads(created.stdout)["manifest_file"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sessions"][0]["archive_file"] = str(tmp_path / "outside-session-archive.jsonl")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    result = session_archive.verify_archive(manifest_path)
    assert result["summary"]["ok"] == 1
    assert result["summary"]["failed"] == 0


def test_verify_rejects_absolute_archive_relative_path_without_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project="/work/atomic", session_id="thread-1", payload="archive me")
    created = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        "/work/atomic",
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--json",
    )
    manifest_path = Path(json.loads(created.stdout)["manifest_file"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sessions"][0]["archive_file"] = str(archive_root / "outside.jsonl")
    manifest["sessions"][0]["archive_relative_path"] = str(tmp_path / "outside.jsonl")

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def forbidden_hash(path: Path) -> str:
        raise AssertionError(f"hash called on disallowed path: {path}")

    monkeypatch.setattr(session_archive, "sha256_file", forbidden_hash)

    result = session_archive.verify_archive(manifest_path)
    assert result["summary"]["failed"] == 1
    assert result["sessions"][0]["errors"] == ["archive path escapes manifest directory"]


def test_verify_rejects_dotdot_archive_relative_path_without_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project="/work/atomic", session_id="thread-1", payload="archive me")
    created = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        "/work/atomic",
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--json",
    )
    manifest_path = Path(json.loads(created.stdout)["manifest_file"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sessions"][0]["archive_file"] = str(archive_root / "outside.jsonl")
    manifest["sessions"][0]["archive_relative_path"] = "../outside.jsonl"

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def forbidden_hash(path: Path) -> str:
        raise AssertionError(f"hash called on disallowed path: {path}")

    monkeypatch.setattr(session_archive, "sha256_file", forbidden_hash)

    result = session_archive.verify_archive(manifest_path)
    assert result["summary"]["failed"] == 1
    assert result["sessions"][0]["errors"] == ["archive path escapes manifest directory"]


def test_verify_rejects_in_archive_symlink_to_outside_sentinel_without_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project="/work/atomic", session_id="thread-1", payload="archive me")
    created = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        "/work/atomic",
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--json",
    )
    manifest_payload = json.loads(created.stdout)
    manifest_path = Path(manifest_payload["manifest_file"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sentinel = tmp_path / "outside-sentinel.jsonl"
    sentinel.write_text("outside\n", encoding="utf-8")
    escaped = manifest_path.parent / "escaped.jsonl"
    escaped.symlink_to(sentinel)
    manifest["sessions"][0]["archive_file"] = manifest_payload["sessions"][0]["archive_file"]
    manifest["sessions"][0]["archive_relative_path"] = str(escaped.name)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def forbidden_hash(path: Path) -> str:
        raise AssertionError(f"hash called on disallowed path: {path}")

    monkeypatch.setattr(session_archive, "sha256_file", forbidden_hash)

    result = session_archive.verify_archive(manifest_path)
    assert result["summary"]["failed"] == 1
    assert result["sessions"][0]["errors"] == ["archive path escapes manifest directory"]


def test_prune_requires_verified_archive_and_confirmation(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project=project, session_id="thread-1", payload="archive me")
    created = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        project,
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--json",
    )
    manifest_path = Path(json.loads(created.stdout)["manifest_file"])

    missing_confirmation = run_archive(
        "prune-local",
        "--manifest",
        str(manifest_path),
        "--allow-codex-running",
        "--json",
    )

    assert missing_confirmation.returncode == 1
    assert source.exists()
    assert "confirm" in missing_confirmation.stderr.lower()

    pruned = run_archive(
        "prune-local",
        "--manifest",
        str(manifest_path),
        "--confirm-prune-local",
        "--allow-codex-running",
        "--json",
    )

    assert pruned.returncode == 0, pruned.stderr
    payload = json.loads(pruned.stdout)
    assert payload["summary"]["deleted_count"] == 1
    assert payload["sessions"][0]["status"] == "deleted"
    assert not source.exists()


def test_prune_refuses_when_archived_copy_fails_verification(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project=project, session_id="thread-1", payload="archive me")
    created = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        project,
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--json",
    )
    manifest_path = Path(json.loads(created.stdout)["manifest_file"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    Path(manifest["sessions"][0]["archive_file"]).write_text(
        "tampered\n", encoding="utf-8"
    )

    pruned = run_archive(
        "prune-local",
        "--manifest",
        str(manifest_path),
        "--confirm-prune-local",
        "--allow-codex-running",
        "--json",
    )

    assert pruned.returncode == 1
    assert "archive verification failed" in pruned.stderr
    assert source.exists()


def test_prune_refuses_tampered_manifest_source_outside_session_root(
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project=project, session_id="thread-1", payload="archive me")
    created = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        project,
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--json",
    )
    manifest_path = Path(json.loads(created.stdout)["manifest_file"])
    outside_file = tmp_path / "do-not-delete.txt"
    outside_file.write_text("keep me\n", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sessions"][0]["source_file"] = str(outside_file)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    pruned = run_archive(
        "prune-local",
        "--manifest",
        str(manifest_path),
        "--confirm-prune-local",
        "--allow-codex-running",
        "--json",
    )

    assert pruned.returncode == 3
    payload = json.loads(pruned.stdout)
    assert payload["summary"]["failed_count"] == 1
    assert payload["sessions"][0]["status"] == "failed"
    assert outside_file.exists()


def test_prune_local_sessions_preflights_all_sources_and_leaves_files_untouched_on_failure(
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source1 = session_root / "2026" / "01" / "02" / "thread1.jsonl"
    source2 = session_root / "2026" / "01" / "02" / "thread2.jsonl"
    write_session(source1, project=project, session_id="thread-1", payload="x" * 1200)
    write_session(source2, project=project, session_id="thread-2", payload="x" * 1200)
    created = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        project,
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--json",
    )
    manifest_path = Path(json.loads(created.stdout)["manifest_file"])

    source1.write_text(source1.read_text(encoding="utf-8") + "\nappended", encoding="utf-8")

    result = session_archive.prune_local_sessions(
        manifest_file=manifest_path,
        confirm_prune_local=True,
    )

    assert result["summary"]["deleted_count"] == 0
    assert result["summary"]["failed_count"] == 1
    assert source1.exists()
    assert source2.exists()
    statuses = {entry["source_file"]: entry["status"] for entry in result["sessions"]}
    assert statuses[str(source1.resolve())] == "failed"
    assert statuses[str(source2.resolve())] == "restored"


def test_prune_local_sessions_uses_quarantine_and_rolls_back_on_staged_validation_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source1 = session_root / "2026" / "01" / "02" / "thread1.jsonl"
    source2 = session_root / "2026" / "01" / "02" / "thread2.jsonl"
    write_session(source1, project=project, session_id="thread-1", payload="x" * 1200)
    write_session(source2, project=project, session_id="thread-2", payload="x" * 1200)
    created = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        project,
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--json",
    )
    manifest_path = Path(json.loads(created.stdout)["manifest_file"])

    original_hash = session_archive.sha256_file

    def tamper_quarantined_hash(path: Path) -> str:
        if ".codex-thread-tools-prune-" in str(path):
            return "bad-" + original_hash(path)
        return original_hash(path)

    monkeypatch.setattr(session_archive, "sha256_file", tamper_quarantined_hash)

    result = session_archive.prune_local_sessions(
        manifest_file=manifest_path,
        confirm_prune_local=True,
    )

    assert result["summary"]["deleted_count"] == 0
    assert result["summary"]["failed_count"] == 1
    assert source1.exists()
    assert source2.exists()
    assert result["sessions"][0]["status"] == "restored"
    assert "session source metadata changed" in result["sessions"][0]["error"]
    assert "recovery_file" not in result["sessions"][0]
    assert result["sessions"][1]["status"] == "restored"
    assert not any(
        ".codex-thread-tools-quarantine-" in path.name
        for path in (session_root / "2026" / "01" / "02").iterdir()
    )


def test_format_prune_includes_failed_count_and_file_errors() -> None:
    result = {
        "manifest_file": "/tmp/manifest.json",
        "summary": {
            "deleted_count": 0,
            "missing_count": 1,
            "failed_count": 2,
        },
        "sessions": [
            {
                "source_file": "/tmp/source1",
                "status": "failed",
                "error": "staging failed",
                "recovery_file": "/tmp/recovery/source1",
            },
            {"source_file": "/tmp/source2", "status": "missing"},
            {"source_file": "/tmp/source3", "status": "failed", "error": "mismatch"},
            {
                "source_file": "/tmp/source4",
                "status": "restored",
                "error": "session source metadata changed: hash mismatch",
            },
        ],
    }

    output = session_archive.format_prune(result)

    assert "Failed: 2" in output
    assert "FAILED /tmp/source1: staging failed" in output
    assert "Recovery: /tmp/recovery/source1" in output
    assert "FAILED /tmp/source3: mismatch" in output
    assert "RESTORED /tmp/source4: session source metadata changed: hash mismatch" in output


def _load_session_cli() -> object:
    spec = importlib.util.spec_from_file_location(
        "codex_session_archive_cli",
        str(ROOT / "tools" / "codex-session-archive.py"),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load session cli module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archive_refuses_archive_root_inside_session_root(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project="/work/atomic", session_id="thread-1", payload="archive me")

    result = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        "/work/atomic",
        "--archive-root",
        str(session_root / "archive"),
    )

    assert result.returncode == 1
    assert "archive root must be outside the session root" in result.stderr


def test_session_archive_slug_preserves_expected_output() -> None:
    assert session_archive.session_archive_slug("/Users/example/My Project") == "My-Project"
    assert session_archive.session_archive_slug("Project.Name_v1") == "Project.Name_v1"


def _generated_siblings(base: Path) -> list[Path]:
    return [
        path
        for path in base.iterdir()
        if path.name.startswith(".codex-thread-tools-staging-")
        or path.name.startswith(".codex-thread-tools-backup-")
    ]


def test_archive_force_cleans_stale_archived_files_in_target(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"

    huge = session_root / "2026" / "01" / "01" / "huge.jsonl"
    tiny = session_root / "2026" / "01" / "01" / "tiny.jsonl"
    write_session(huge, project=project, session_id="huge", payload="x" * 5000)
    write_session(tiny, project=project, session_id="tiny", payload="small")

    first = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        project,
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--json",
    )
    assert first.returncode == 0, first.stderr
    first_payload = json.loads(first.stdout)
    archive_dir = Path(first_payload["archive_dir"])
    first_tiny = archive_dir / "sessions" / str(tiny.resolve().relative_to(session_root.resolve()))
    assert first_tiny.exists()

    second = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        project,
        "--min-size",
        "1KiB",
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--force",
        "--json",
    )
    assert second.returncode == 0, second.stderr
    second_payload = json.loads(second.stdout)
    second_manifest = Path(second_payload["manifest_file"])
    installed = json.loads(second_manifest.read_text(encoding="utf-8"))

    assert second_payload["archive_dir"] == str(archive_dir)
    assert second_payload["sessions"][0]["archive_file"].startswith(str(archive_dir))
    assert second_payload["summary"]["archived_count"] == 1
    assert second_payload["sessions"][0]["session_id"] == "huge"
    assert not first_tiny.exists()
    assert second_manifest.exists()
    assert installed["summary"]["archived_count"] == 1

    verify = run_archive("verify", "--manifest", str(second_manifest), "--json")
    assert verify.returncode == 0, verify.stderr
    verify_payload = json.loads(verify.stdout)
    assert verify_payload["summary"]["failed"] == 0


def test_archive_force_preserves_existing_archive_when_staging_fails(tmp_path: Path, monkeypatch) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"

    source1 = session_root / "2026" / "01" / "01" / "good.jsonl"
    source2 = session_root / "2026" / "01" / "01" / "also-good.jsonl"
    write_session(source1, project=project, session_id="good", payload="x" * 2048)
    write_session(source2, project=project, session_id="also-good", payload="x" * 2048)

    created = run_archive(
        "archive",
        "--session-root",
        str(session_root),
        "--project",
        project,
        "--archive-root",
        str(archive_root),
        "--archive-name",
        "atomic-test",
        "--json",
    )
    assert created.returncode == 0, created.stderr
    manifest_path = Path(json.loads(created.stdout)["manifest_file"])
    archive_dir = manifest_path.parent
    original_manifest_bytes = manifest_path.read_bytes()
    original_archive_bytes = (archive_dir / "sessions" / str(source1.resolve().relative_to(session_root.resolve()))).read_bytes()

    copy_calls = 0
    original_copy = session_archive.shutil.copy2

    def fail_on_first_copy(*args, **kwargs):
        nonlocal copy_calls
        copy_calls += 1
        if copy_calls == 1:
            raise RuntimeError("forced failure")
        return original_copy(*args, **kwargs)

    monkeypatch.setattr(session_archive.shutil, "copy2", fail_on_first_copy)

    with pytest.raises(RuntimeError):
        session_archive.archive_sessions(
            session_root=session_root,
            archive_root=archive_root,
            project=project,
            older_than=None,
            min_size=None,
            archive_name="atomic-test",
            now=None,
            force=True,
        )

    assert manifest_path.exists()
    assert manifest_path.read_bytes() == original_manifest_bytes
    assert (archive_dir / "sessions" / str(source1.resolve().relative_to(session_root.resolve()))).read_bytes() == original_archive_bytes
    assert not _generated_siblings(archive_root / "codex-session-archives")


def test_archive_rejects_unsafe_archive_name(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "01" / "safe.jsonl"
    write_session(source, project=project, session_id="safe", payload="x" * 1200)

    unsafe_names = [
        "../outside",
        "..",
        ".",
        "/tmp/escape",
        "a/b",
        "a\\b",
        "name\x00bad",
    ]
    for archive_name in unsafe_names:
        with pytest.raises(ValueError, match="unsafe archive name"):
            session_archive.archive_sessions(
                session_root=session_root,
                archive_root=archive_root,
                project=project,
                older_than=None,
                min_size=None,
                archive_name=archive_name,
                now=None,
                force=False,
            )


def test_archive_allows_safe_single_component_names(tmp_path: Path) -> None:
    assert session_archive.validate_archive_name("July Archive") == "July Archive"
    assert session_archive.validate_archive_name("July-Archive_01") == "July-Archive_01"


def test_archive_rejects_target_symlink_outside_archive_container(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "01" / "safe.jsonl"
    write_session(source, project=project, session_id="safe", payload="x" * 1200)
    outside = tmp_path / "outside-target"
    outside.mkdir(parents=True)
    (outside / "outside-archive.txt").write_text("do-not-touch", encoding="utf-8")

    container = archive_root / "codex-session-archives"
    container.mkdir(parents=True)
    target = container / "atomic-test"
    target.symlink_to(outside)

    with pytest.raises(ValueError, match="target is a symlink"):
        session_archive.archive_sessions(
            session_root=session_root,
            archive_root=archive_root,
            project=project,
            older_than=None,
            min_size=None,
            archive_name="atomic-test",
            now=None,
            force=True,
        )

    assert (outside / "outside-archive.txt").exists()


def test_archive_rejects_dangling_target_symlink(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "01" / "safe.jsonl"
    write_session(source, project=project, session_id="safe", payload="x" * 1200)

    container = archive_root / "codex-session-archives"
    container.mkdir(parents=True)
    target = container / "atomic-test"
    target.symlink_to(tmp_path / "outside-target" / "missing.jsonl")

    with pytest.raises(ValueError, match="target is a symlink"):
        session_archive.archive_sessions(
            session_root=session_root,
            archive_root=archive_root,
            project=project,
            older_than=None,
            min_size=None,
            archive_name="atomic-test",
            now=None,
            force=True,
        )


def test_archive_rejects_symlinked_archive_container(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "01" / "safe.jsonl"
    write_session(source, project=project, session_id="safe", payload="x" * 1200)

    container_target = tmp_path / "other-container"
    container_target.mkdir(parents=True)
    (container_target / "outside.txt").write_text("do-not-touch", encoding="utf-8")
    container = archive_root / "codex-session-archives"
    archive_root.mkdir(parents=True, exist_ok=True)
    container.symlink_to(container_target)

    with pytest.raises(ValueError, match="archive container is a symlink"):
        session_archive.archive_sessions(
            session_root=session_root,
            archive_root=archive_root,
            project=project,
            older_than=None,
            min_size=None,
            archive_name="atomic-test",
            now=None,
            force=True,
        )

    assert (container_target / "outside.txt").exists()


def test_archive_writes_final_paths_to_manifest_and_markdown(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "01" / "thread.jsonl"
    write_session(source, project=project, session_id="thread-1", payload="x" * 1200)

    payload = session_archive.archive_sessions(
        session_root=session_root,
        archive_root=archive_root,
        project=project,
        older_than=None,
        min_size=None,
        archive_name="atomic-test",
        now=None,
        force=False,
    )

    manifest_path = Path(payload["manifest_file"])
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    markdown_path = Path(payload["manifest_file"]).parent / "manifest.md"
    markdown = markdown_path.read_text(encoding="utf-8")
    assert Path(manifest_data["archive_dir"]) == Path(payload["archive_dir"])
    assert Path(manifest_data["manifest_file"]) == Path(payload["manifest_file"])
    assert Path(manifest_data["sessions"][0]["archive_file"]) == Path(
        payload["sessions"][0]["archive_file"]
    )
    assert ".codex-thread-tools-staging-" not in manifest_path.read_text(encoding="utf-8")
    assert ".codex-thread-tools-staging-" not in markdown

    verify = session_archive.verify_archive(manifest_path)
    assert verify["summary"]["ok"] == 1
    assert verify["summary"]["failed"] == 0


def test_archive_force_preserves_backup_on_restore_failure(tmp_path: Path, monkeypatch) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"

    source = session_root / "2026" / "01" / "01" / "thread.jsonl"
    write_session(source, project=project, session_id="thread", payload="x" * 1200)

    created = session_archive.archive_sessions(
        session_root=session_root,
        archive_root=archive_root,
        project=project,
        older_than=None,
        min_size=None,
        archive_name="atomic-test",
        now=None,
        force=False,
    )
    manifest_path = Path(created["manifest_file"])
    archive_dir = manifest_path.parent
    original_manifest_bytes = manifest_path.read_bytes()
    archived_file = archive_dir / "sessions" / str(source.resolve().relative_to(session_root.resolve()))
    original_archive_bytes = archived_file.read_bytes()

    original_rename = Path.rename

    def failing_rename(self, target):  # type: ignore[override]
        if (
            ".codex-thread-tools-staging-" in str(self)
            and Path(target).name == "atomic-test"
            and "atomic-test" in str(target)
        ):
            raise RuntimeError("forced install failure")
        if ".codex-thread-tools-backup-" in self.name:
            raise RuntimeError("forced restore failure")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", failing_rename)

    with pytest.raises(RuntimeError, match="failed to restore backup"):
        session_archive.archive_sessions(
            session_root=session_root,
            archive_root=archive_root,
            project=project,
            older_than=None,
            min_size=None,
            archive_name="atomic-test",
            now=None,
            force=True,
        )

    siblings = _generated_siblings(archive_root / "codex-session-archives")
    backups = [path for path in siblings if path.name.startswith(".codex-thread-tools-backup-")]
    assert len(backups) == 1
    backup = backups[0]
    assert backup.is_dir()
    assert (backup / "manifest.json").read_bytes() == original_manifest_bytes
    assert (backup / "sessions" / str(source.resolve().relative_to(session_root.resolve()))).read_bytes() == original_archive_bytes


def test_archive_cleanup_runs_for_baseexception_and_restores_original_archive(tmp_path: Path, monkeypatch) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"

    source = session_root / "2026" / "01" / "01" / "thread.jsonl"
    write_session(source, project=project, session_id="thread", payload="x" * 1200)

    created = session_archive.archive_sessions(
        session_root=session_root,
        archive_root=archive_root,
        project=project,
        older_than=None,
        min_size=None,
        archive_name="atomic-test",
        now=None,
        force=False,
    )
    manifest_path = Path(created["manifest_file"])
    archive_dir = manifest_path.parent
    original_manifest_bytes = manifest_path.read_bytes()
    archived_file = archive_dir / "sessions" / str(source.resolve().relative_to(session_root.resolve()))
    original_archive_bytes = archived_file.read_bytes()

    original_copy = session_archive.shutil.copy2

    class _BuildAbort(BaseException):
        pass

    def fail_copy(*args, **kwargs):
        raise _BuildAbort("forced")

    monkeypatch.setattr(session_archive.shutil, "copy2", fail_copy)

    with pytest.raises(_BuildAbort):
        session_archive.archive_sessions(
            session_root=session_root,
            archive_root=archive_root,
            project=project,
            older_than=None,
            min_size=None,
            archive_name="atomic-test",
            now=None,
            force=True,
        )

    assert not _generated_siblings(archive_root / "codex-session-archives")
    assert manifest_path.exists()
    assert manifest_path.read_bytes() == original_manifest_bytes
    assert archived_file.read_bytes() == original_archive_bytes

    monkeypatch.setattr(session_archive.shutil, "copy2", original_copy)

    class _InstallAbort(BaseException):
        pass

    original_rename = Path.rename

    def fail_install(self, target):  # type: ignore[override]
        if (
            ".codex-thread-tools-staging-" in self.name
            and target == archive_dir
        ):
            raise _InstallAbort("forced")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_install)
    with pytest.raises(_InstallAbort):
        session_archive.archive_sessions(
            session_root=session_root,
            archive_root=archive_root,
            project=project,
            older_than=None,
            min_size=None,
            archive_name="atomic-test",
            now=None,
            force=True,
        )

    assert manifest_path.read_bytes() == original_manifest_bytes
    assert archived_file.read_bytes() == original_archive_bytes
    assert not _generated_siblings(archive_root / "codex-session-archives")


def test_archive_preserves_backup_if_baseexception_during_restore(tmp_path: Path, monkeypatch) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"

    source = session_root / "2026" / "01" / "01" / "thread.jsonl"
    write_session(source, project=project, session_id="thread", payload="x" * 1200)

    created = session_archive.archive_sessions(
        session_root=session_root,
        archive_root=archive_root,
        project=project,
        older_than=None,
        min_size=None,
        archive_name="atomic-test",
        now=None,
        force=False,
    )
    manifest_path = Path(created["manifest_file"])
    archive_dir = manifest_path.parent
    original_manifest_bytes = manifest_path.read_bytes()
    archived_file = archive_dir / "sessions" / str(source.resolve().relative_to(session_root.resolve()))
    original_archive_bytes = archived_file.read_bytes()

    original_rename = Path.rename

    class _RestoreAbort(BaseException):
        pass

    def fail_restore(self, target):  # type: ignore[override]
        if ".codex-thread-tools-staging-" in str(self):
            raise RuntimeError("forced install failure")
        if ".codex-thread-tools-backup-" in self.name:
            raise _RestoreAbort("forced restore failure")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_restore)

    with pytest.raises(RuntimeError, match="failed to restore backup"):
        session_archive.archive_sessions(
            session_root=session_root,
            archive_root=archive_root,
            project=project,
            older_than=None,
            min_size=None,
            archive_name="atomic-test",
            now=None,
            force=True,
        )

    siblings = _generated_siblings(archive_root / "codex-session-archives")
    backups = [path for path in siblings if path.name.startswith(".codex-thread-tools-backup-")]
    assert len(backups) == 1
    backup = backups[0]
    assert backup.is_dir()
    assert (backup / "manifest.json").read_bytes() == original_manifest_bytes
    assert (backup / "sessions" / str(source.resolve().relative_to(session_root.resolve()))).read_bytes() == original_archive_bytes


def test_atomic_directory_temporaries_are_not_left_behind_after_success_and_failure(tmp_path: Path, monkeypatch) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "01" / "keep.jsonl"
    write_session(source, project=project, session_id="keep", payload="x" * 1200)

    created = session_archive.archive_sessions(
        session_root=session_root,
        archive_root=archive_root,
        project=project,
        older_than=None,
        min_size=None,
        archive_name="atomic-success",
        now=None,
        force=False,
    )
    staging_root = archive_root / "codex-session-archives"
    assert Path(created["archive_dir"]).exists()
    assert not _generated_siblings(staging_root)

    def always_fail(*args, **kwargs):
        raise RuntimeError("forced")

    monkeypatch.setattr(session_archive.shutil, "copy2", always_fail)
    with pytest.raises(RuntimeError):
        session_archive.archive_sessions(
            session_root=session_root,
            archive_root=archive_root,
            project=project,
            older_than=None,
            min_size=None,
            archive_name="atomic-success",
            now=None,
            force=True,
        )

    assert not _generated_siblings(staging_root)


def test_atomic_directory_remove_path_unlinks_files_and_symlinks_without_following_targets(
    tmp_path: Path,
) -> None:
    staged_file = tmp_path / "to-cleanup"
    staged_file.write_text("keep target", encoding="utf-8")

    target_file = tmp_path / "target.txt"
    target_file.write_text("preserve", encoding="utf-8")
    staged_link = tmp_path / "file-link.txt"
    staged_link.symlink_to(target_file)

    target_dir = tmp_path / "target-dir"
    target_dir.mkdir()
    (target_dir / "keep.txt").write_text("preserve", encoding="utf-8")
    staged_dir_link = tmp_path / "dir-link"
    staged_dir_link.symlink_to(target_dir)

    _remove_path(staged_file)
    _remove_path(staged_link)
    _remove_path(staged_dir_link)

    assert not staged_file.exists()
    assert not staged_link.exists()
    assert not staged_dir_link.exists()
    assert target_file.exists()
    assert target_dir.exists()


def test_staged_directory_generates_neutral_temporary_names(tmp_path: Path) -> None:
    target = tmp_path / "visual-archive" / "final"
    with staged_directory(target, replace=False) as staging:
        temp_names = {
            path.name
            for path in tmp_path.rglob(".codex-thread-tools-staging-*")
            if path.is_dir() or path.is_file() or path.is_symlink()
        }
        assert len(temp_names) == 1
    staging_name = next(iter(temp_names))
    assert "visual-archive" not in staging_name
    assert staging_name.startswith(".codex-thread-tools-staging-")
    assert str(staging) == str(staging.parent / staging_name)


def test_session_archive_cli_reports_runtime_failures_without_traceback(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    cli = _load_session_cli()
    monkeypatch.setattr(
        cli.session_archive,
        "archive_sessions",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("runtime failure")),
    )

    code = cli.main(
        [
            "archive",
            "--session-root",
            str(tmp_path),
            "--archive-root",
            str(tmp_path),
            "--force",
        ]
    )
    output = capsys.readouterr()

    assert code == 1
    assert output.err.strip() == "error: runtime failure"
    assert "Traceback" not in output.err


def test_staged_directory_race_to_existing_target_is_detected_and_target_survives(
    tmp_path: Path,
) -> None:
    target = tmp_path / "session-archive" / "final"

    with pytest.raises(ValueError, match="archive already exists"):
        with staged_directory(target, replace=False) as _staging:
            target.write_text("late-arrival", encoding="utf-8")

    assert target.exists()
    assert target.read_text(encoding="utf-8") == "late-arrival"
    assert not _generated_siblings(target.parent)


def test_staged_directory_existing_target_leaves_reusable_lock_file(tmp_path: Path) -> None:
    target = tmp_path / "session-archive" / "final"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text("existing\n", encoding="utf-8")

    with pytest.raises(ValueError, match="archive already exists"):
        with staged_directory(target, replace=False):
            pass

    assert _reservation_path(target).is_file()


def test_staged_directory_recovers_stale_reservation(tmp_path: Path) -> None:
    target = tmp_path / "session-archive" / "final"
    target.parent.mkdir(parents=True)
    reservation = _reservation_path(target)
    reservation.write_text("pid=99999999\n", encoding="utf-8")

    with staged_directory(target, replace=False) as staging:
        (staging / "manifest.json").write_text("new\n", encoding="utf-8")

    assert (target / "manifest.json").read_text(encoding="utf-8") == "new\n"
    assert reservation.exists()


def test_staged_directory_recovers_incomplete_unlocked_reservation(
    tmp_path: Path,
) -> None:
    target = tmp_path / "session-archive" / "final"
    target.parent.mkdir(parents=True)
    reservation = _reservation_path(target)
    reservation.touch()

    with staged_directory(target, replace=False) as staging:
        (staging / "manifest.json").write_text("new\n", encoding="utf-8")

    assert reservation.exists()
    assert (target / "manifest.json").read_text(encoding="utf-8") == "new\n"


def test_staged_directory_keeps_installed_archive_when_backup_cleanup_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "archive" / "final"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text("old\n", encoding="utf-8")
    original_remove_path = atomic_directory._remove_path

    def fail_backup_cleanup(path: Path) -> None:
        if path.name.startswith(".codex-thread-tools-backup-"):
            raise OSError("backup cleanup denied")
        original_remove_path(path)

    monkeypatch.setattr(atomic_directory, "_remove_path", fail_backup_cleanup)

    with staged_directory(target, replace=True) as staging:
        (staging / "manifest.json").write_text("new\n", encoding="utf-8")

    assert (target / "manifest.json").read_text(encoding="utf-8") == "new\n"
    backups = list(target.parent.glob(".codex-thread-tools-backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "manifest.json").read_text(encoding="utf-8") == "old\n"


def test_reservation_uses_buffered_writes_after_fdopen(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "archive" / "final"

    def forbid_raw_write(*_args, **_kwargs) -> None:
        raise AssertionError("raw descriptor writes are not allowed after fdopen")

    monkeypatch.setattr(atomic_directory.os, "write", forbid_raw_write)

    with atomic_directory.target_reservation(target):
        metadata = _reservation_path(target).read_text(encoding="ascii")

    assert f"pid={os.getpid()}" in metadata


def test_reservation_metadata_is_written_while_lock_is_held(tmp_path: Path) -> None:
    target = tmp_path / "session-archive" / "final"

    with staged_directory(target, replace=False) as staging:
        metadata = _reservation_path(target).read_text(encoding="ascii")
        assert f"pid={os.getpid()}" in metadata
        assert "created_ns=" in metadata
        (staging / "manifest.json").write_text("new\n", encoding="utf-8")


def test_active_reservation_cannot_be_stolen_using_stale_metadata(tmp_path: Path) -> None:
    target = tmp_path / "session-archive" / "final"
    ready = tmp_path / "ready"
    stop = tmp_path / "stop"
    script = """
import sys
import time
from pathlib import Path
from codex_thread_tools.atomic_directory import _reservation_path, target_reservation

target, ready, stop = map(Path, sys.argv[1:])
with target_reservation(target):
    _reservation_path(target).write_text(
        "pid=99999999\\ncreated_ns=0\\n", encoding="ascii"
    )
    ready.touch()
    while not stop.exists():
        time.sleep(0.01)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(target), str(ready), str(stop)],
        cwd=ROOT,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "reservation holder did not start"

        with pytest.raises(ValueError, match="reserved by another process"):
            with atomic_directory.target_reservation(target):
                pass
    finally:
        stop.touch()
        process.wait(timeout=5)


def test_prune_rollback_preserves_new_file_at_original_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project=project, session_id="thread-1", payload="archive me")
    created = session_archive.archive_sessions(
        session_root=session_root,
        archive_root=archive_root,
        project=project,
        older_than=None,
        min_size=None,
        archive_name="atomic-test",
    )
    manifest_path = Path(created["manifest_file"])
    original_assert = session_archive._assert_source_matches_plan

    def replace_during_staged_validation(path, item, *, compare_identity):
        if ".codex-thread-tools-prune-" in str(path):
            source.write_text("new active session\n", encoding="utf-8")
            raise RuntimeError("forced staged validation failure")
        return original_assert(path, item, compare_identity=compare_identity)

    monkeypatch.setattr(
        session_archive,
        "_assert_source_matches_plan",
        replace_during_staged_validation,
    )

    result = session_archive.prune_local_sessions(
        manifest_file=manifest_path,
        confirm_prune_local=True,
    )

    assert source.read_text(encoding="utf-8") == "new active session\n"
    failed = result["sessions"][0]
    assert failed["status"] == "failed"
    recovery_file = Path(failed["recovery_file"])
    assert recovery_file.is_file()
    assert recovery_file != source


def test_prune_restores_source_after_quarantined_delete_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project=project, session_id="thread-1", payload="archive me")
    created = session_archive.archive_sessions(
        session_root=session_root,
        archive_root=archive_root,
        project=project,
        older_than=None,
        min_size=None,
        archive_name="atomic-test",
    )
    manifest_path = Path(created["manifest_file"])
    original_unlink = Path.unlink

    def fail_quarantined_delete(path: Path, *args, **kwargs):
        if ".codex-thread-tools-prune-" in str(path) and path.suffix == ".jsonl":
            raise OSError("delete denied")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_quarantined_delete)

    result = session_archive.prune_local_sessions(
        manifest_file=manifest_path,
        confirm_prune_local=True,
    )

    entry = result["sessions"][0]
    assert result["summary"]["deleted_count"] == 0
    assert result["summary"]["failed_count"] == 1
    assert source.is_file()
    assert entry["status"] == "restored"
    assert "failed to delete quarantined source: delete denied" in entry["error"]
    assert "recovery_file" not in entry


def test_prune_keeps_recovery_file_when_delete_failure_cannot_restore_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project=project, session_id="thread-1", payload="archive me")
    created = session_archive.archive_sessions(
        session_root=session_root,
        archive_root=archive_root,
        project=project,
        older_than=None,
        min_size=None,
        archive_name="atomic-test",
    )
    manifest_path = Path(created["manifest_file"])
    original_unlink = Path.unlink

    def replace_source_then_fail_delete(path: Path, *args, **kwargs):
        if ".codex-thread-tools-prune-" in str(path) and path.suffix == ".jsonl":
            source.write_text("new active session\n", encoding="utf-8")
            raise OSError("delete denied")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", replace_source_then_fail_delete)

    result = session_archive.prune_local_sessions(
        manifest_file=manifest_path,
        confirm_prune_local=True,
    )

    entry = result["sessions"][0]
    assert result["summary"]["deleted_count"] == 0
    assert result["summary"]["failed_count"] == 1
    assert source.read_text(encoding="utf-8") == "new active session\n"
    assert entry["status"] == "failed"
    assert "new file exists at the original path" in entry["error"]
    recovery_file = Path(entry["recovery_file"])
    assert recovery_file.is_file()


def test_prune_holds_archive_reservation_through_local_deletion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_root = tmp_path / "sessions"
    archive_root = tmp_path / "archive"
    project = "/work/atomic"
    source = session_root / "2026" / "01" / "02" / "thread.jsonl"
    write_session(source, project=project, session_id="thread-1", payload="archive me")
    created = session_archive.archive_sessions(
        session_root=session_root,
        archive_root=archive_root,
        project=project,
        older_than=None,
        min_size=None,
        archive_name="atomic-test",
    )
    manifest_path = Path(created["manifest_file"])
    original_unlink = Path.unlink
    attempted = False

    def attempt_replace_while_deleting(path: Path, *args, **kwargs):
        nonlocal attempted
        if ".codex-thread-tools-prune-" in str(path) and not attempted:
            attempted = True
            with pytest.raises(ValueError, match="reserved by another process"):
                session_archive.archive_sessions(
                    session_root=session_root,
                    archive_root=archive_root,
                    project=project,
                    older_than=None,
                    min_size=None,
                    archive_name="atomic-test",
                    force=True,
                )
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", attempt_replace_while_deleting)

    result = session_archive.prune_local_sessions(
        manifest_file=manifest_path,
        confirm_prune_local=True,
    )

    assert attempted
    assert result["summary"]["deleted_count"] == 1


@pytest.mark.parametrize(
    "manifest_payload",
    (
        [],
        {"type": session_archive.MANIFEST_TYPE, "version": 1, "sessions": [[]]},
        {"type": session_archive.MANIFEST_TYPE, "version": 1, "sessions": [{}]},
    ),
)
def test_session_archive_cli_rejects_malformed_manifests_without_traceback(
    tmp_path: Path,
    manifest_payload,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")

    result = run_archive("verify", "--manifest", str(manifest_path), "--json")

    assert result.returncode == 1
    assert result.stderr.startswith("error:")
    assert "Traceback" not in result.stderr
