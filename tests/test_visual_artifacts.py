from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SESSIONS = FIXTURES / "sessions"
ASSETS = FIXTURES / "visual_assets"


def run_visual(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "codex-visual-archive.py"), *args],
        cwd=ROOT,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_scan_detects_embedded_image_without_writing(tmp_path: Path) -> None:
    result = run_visual(
        "scan",
        str(SESSIONS / "visual-embedded-image.jsonl"),
        "--allow-local-root",
        str(ASSETS),
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"]["occurrences"] == 1
    assert payload["summary"]["embedded"] == 1
    assert payload["summary"]["embedded_bytes"] > 0
    assert payload["artifacts"][0]["status"] == "ready"
    assert not list(tmp_path.iterdir())


def test_scan_detects_local_images_markdown_video_and_errors() -> None:
    local = json.loads(
        run_visual(
            "scan",
            str(SESSIONS / "visual-local-images-event.jsonl"),
            "--allow-local-root",
            str(ASSETS),
            "--json",
        ).stdout
    )
    markdown = json.loads(
        run_visual(
            "scan",
            str(SESSIONS / "visual-markdown-paths.jsonl"),
            "--allow-local-root",
            str(ASSETS),
            "--json",
        ).stdout
    )
    video = json.loads(
        run_visual(
            "scan",
            str(SESSIONS / "visual-video-reference.jsonl"),
            "--allow-local-root",
            str(ASSETS),
            "--json",
        ).stdout
    )
    errors = json.loads(
        run_visual(
            "scan",
            str(SESSIONS / "visual-malformed-and-missing.jsonl"),
            "--allow-local-root",
            str(ASSETS),
            "--json",
        ).stdout
    )

    assert local["summary"]["local_files"] == 1
    assert markdown["summary"]["local_files"] == 3
    assert video["summary"]["videos"] == 2
    assert errors["summary"]["errors"] == 2
    assert errors["summary"]["skipped"] == 1


def test_scan_refuses_symlink_escape_outside_allowed_root() -> None:
    result = run_visual(
        "scan",
        str(SESSIONS / "visual-symlink-escape.jsonl"),
        "--allow-local-root",
        str(ASSETS),
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"]["skipped"] == 1
    assert payload["artifacts"][0]["status"] == "skipped"
    assert "outside allowed roots" in payload["artifacts"][0]["error"]


def test_archive_copies_and_deduplicates_visuals(tmp_path: Path) -> None:
    result = run_visual(
        "archive",
        str(SESSIONS / "visual-duplicates.jsonl"),
        "--archive-root",
        str(tmp_path),
        "--project-name",
        "Visual Project",
        "--artifact-set",
        "duplicate screenshots",
        "--visual-context",
        "Use these screenshots as design references.",
        "--allow-local-root",
        str(ASSETS),
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"]["occurrences"] == 4
    assert payload["summary"]["stored_files"] == 1
    assert Path(payload["manifest_json"]).exists()
    assert Path(payload["manifest_markdown"]).exists()
    assert Path(payload["handoff_snippet"]).exists()

    manifest = json.loads(Path(payload["manifest_json"]).read_text(encoding="utf-8"))
    assert manifest["visual_context"] == "Use these screenshots as design references."
    assert manifest["summary"]["stored_files"] == 1
    assert len({item["archive_path"] for item in manifest["artifacts"] if item["archive_path"]}) == 1


def test_archive_refuses_existing_archive_without_force(tmp_path: Path) -> None:
    args = (
        "archive",
        str(SESSIONS / "visual-embedded-image.jsonl"),
        "--archive-root",
        str(tmp_path),
        "--project-name",
        "Visual Project",
        "--artifact-set",
        "same set",
        "--visual-context",
        "reference",
        "--allow-local-root",
        str(ASSETS),
        "--json",
    )
    first = run_visual(*args)
    second = run_visual(*args)
    forced = run_visual(*args, "--force")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 1
    assert "already exists" in second.stderr
    assert forced.returncode == 0, forced.stderr


def test_archive_refuses_live_session_root_as_archive_root() -> None:
    result = run_visual(
        "archive",
        str(SESSIONS / "visual-embedded-image.jsonl"),
        "--archive-root",
        str(Path.home() / ".codex" / "sessions"),
        "--project-name",
        "Visual Project",
        "--artifact-set",
        "bad root",
        "--visual-context",
        "reference",
        "--json",
    )

    assert result.returncode == 1
    assert "must not be inside the live Codex session root" in result.stderr


def test_verify_reports_missing_archived_file(tmp_path: Path) -> None:
    archived = run_visual(
        "archive",
        str(SESSIONS / "visual-embedded-image.jsonl"),
        "--archive-root",
        str(tmp_path),
        "--project-name",
        "Visual Project",
        "--artifact-set",
        "verify set",
        "--visual-context",
        "reference",
        "--json",
    )
    manifest_path = Path(json.loads(archived.stdout)["manifest_json"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    Path(manifest["artifacts"][0]["archive_path"]).unlink()

    verified = run_visual("verify", str(manifest_path), "--json")

    assert verified.returncode == 2
    payload = json.loads(verified.stdout)
    assert payload["status"] == "warn"
    assert payload["missing_files"] == 1


def test_verify_reports_corrupted_archived_file(tmp_path: Path) -> None:
    archived = run_visual(
        "archive",
        str(SESSIONS / "visual-embedded-image.jsonl"),
        "--archive-root",
        str(tmp_path),
        "--project-name",
        "Visual Project",
        "--artifact-set",
        "corrupt set",
        "--visual-context",
        "reference",
        "--json",
    )
    manifest_path = Path(json.loads(archived.stdout)["manifest_json"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    Path(manifest["artifacts"][0]["archive_path"]).write_bytes(b"corrupt")

    verified = run_visual("verify", str(manifest_path), "--json")

    assert verified.returncode == 2
    payload = json.loads(verified.stdout)
    assert payload["status"] == "warn"
    assert payload["mismatched_files"] == 1


def test_wizard_defaults_to_no_write(tmp_path: Path) -> None:
    result = run_visual(
        "wizard",
        str(SESSIONS / "visual-embedded-image.jsonl"),
        input_text=f"{tmp_path}\nVisual Project\nwizard set\nreference\n\nn\n",
    )

    assert result.returncode == 0, result.stderr
    assert "No archive written" in result.stdout
    assert not any(tmp_path.iterdir())
