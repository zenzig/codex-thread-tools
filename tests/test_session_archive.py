from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


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

    assert pruned.returncode == 1
    assert outside_file.exists()
    assert "outside the manifest session root" in pruned.stderr


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
