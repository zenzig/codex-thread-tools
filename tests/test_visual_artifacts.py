from __future__ import annotations

import json
import pytest
import subprocess
import sys
import shutil
from time import perf_counter
import importlib.util
from pathlib import Path

from codex_thread_tools.visual_artifacts import scan_record_visual_metrics
from codex_thread_tools import visual_artifacts


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


def test_verify_manifest_rejects_non_object_root(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("[]", encoding="utf-8")

    result = visual_artifacts.verify_manifest(manifest_path)

    assert result["status"] == "warn"
    assert result["missing_files"] == 0
    assert result["details"][0]["error"] == "manifest root must be an object"


def test_verify_manifest_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 999,
                "archive_dir": str(tmp_path),
                "artifacts": [],
            }
        )
    )

    result = visual_artifacts.verify_manifest(manifest_path)
    assert result["status"] == "warn"
    assert result["missing_files"] == 0
    assert result["details"][0]["error"] == "unsupported manifest schema_version: 999"


def test_verify_manifest_rejects_non_list_artifacts(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"schema_version": 1, "archive_dir": str(tmp_path), "artifacts": {}})
    )

    result = visual_artifacts.verify_manifest(manifest_path)
    assert result["status"] == "warn"
    assert result["missing_files"] == 0
    assert result["details"][0]["error"] == "manifest artifacts must be a list"


def test_verify_manifest_rejects_missing_archive_directory(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )

    result = visual_artifacts.verify_manifest(manifest_path)

    assert result["status"] == "warn"
    assert result["details"][0]["error"] == "manifest archive_dir must be a path"


def test_verify_manifest_rejects_copied_entry_without_required_metadata(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "archive_dir": str(tmp_path),
                "artifacts": [
                    {
                        "artifact_id": "a1",
                        "status": "copied",
                        "archive_relative_path": "artifacts/a1.bin",
                    }
                ],
            }
        )
    )

    result = visual_artifacts.verify_manifest(manifest_path)
    assert result["status"] == "warn"
    assert result["details"][0]["error"] in {
        "archive manifest has invalid byte metadata",
        "archive manifest has invalid hash metadata",
    }


def test_verify_manifest_cli_report_warn_status_on_bad_schema(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    result = run_visual("verify", str(manifest_path), "--json")

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "warn"
    assert payload["missing_files"] == 0


def test_verify_manifest_default_output_remains_pretty(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    result = run_visual("verify", str(manifest_path))

    assert result.returncode == 2
    assert result.stdout.startswith("Codex Visual Archive Verify\n")


def test_verify_manifest_rejects_ready_entry_without_archive_metadata(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "archive_dir": str(tmp_path),
                "artifacts": [{"artifact_id": "a1", "status": "ready"}],
            }
        ),
        encoding="utf-8",
    )

    result = visual_artifacts.verify_manifest(manifest_path)

    assert result["status"] == "warn"
    assert result["details"][0]["error"] == "missing archive path metadata"


@pytest.mark.parametrize(
    "artifact",
    ({}, {"artifact_id": "a1", "status": "unknown"}),
)
def test_verify_manifest_rejects_malformed_artifact_entries(
    tmp_path: Path,
    artifact: dict,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "archive_dir": str(tmp_path),
                "artifacts": [artifact],
            }
        ),
        encoding="utf-8",
    )

    result = visual_artifacts.verify_manifest(manifest_path)

    assert result["status"] == "warn"
    assert "status" in result["details"][0]["error"]


def _load_visual_cli() -> object:
    spec = importlib.util.spec_from_file_location(
        "codex_visual_archive_cli",
        str(ROOT / "tools" / "codex-visual-archive.py"),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load visual archive cli module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_rejects_absolute_archive_relative_path_without_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
    manifest["artifacts"][0]["archive_path"] = str((tmp_path / "outside.jsonl"))
    manifest["artifacts"][0]["archive_relative_path"] = str(tmp_path / "outside.jsonl")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def forbidden_hash(_path: Path) -> str:
        raise AssertionError("hash called on disallowed path")

    monkeypatch.setattr(visual_artifacts, "sha256_file", forbidden_hash)

    verified = visual_artifacts.verify_manifest(manifest_path)

    assert verified["status"] == "warn"
    assert verified["missing_files"] == 1
    assert verified["details"][0]["error"] == "archive path escapes manifest directory"


def test_verify_rejects_dotdot_archive_relative_path_without_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
    manifest["artifacts"][0]["archive_relative_path"] = "../outside.jsonl"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def forbidden_hash(_path: Path) -> str:
        raise AssertionError("hash called on disallowed path")

    monkeypatch.setattr(visual_artifacts, "sha256_file", forbidden_hash)

    verified = visual_artifacts.verify_manifest(manifest_path)

    assert verified["status"] == "warn"
    assert verified["missing_files"] == 1
    assert verified["details"][0]["error"] == "archive path escapes manifest directory"


def test_verify_rejects_in_archive_symlink_to_outside_sentinel_without_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
    sentinel = tmp_path / "outside-sentinel.jsonl"
    sentinel.write_text("outside\n", encoding="utf-8")
    escaped = manifest_path.parent / "escaped.jsonl"
    escaped.symlink_to(sentinel)
    manifest["artifacts"][0]["archive_relative_path"] = "escaped.jsonl"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def forbidden_hash(_path: Path) -> str:
        raise AssertionError("hash called on disallowed path")

    monkeypatch.setattr(visual_artifacts, "sha256_file", forbidden_hash)

    verified = visual_artifacts.verify_manifest(manifest_path)

    assert verified["status"] == "warn"
    assert verified["missing_files"] == 1
    assert verified["details"][0]["error"] == "archive path escapes manifest directory"


def test_visual_archive_cli_reports_runtime_failures_without_traceback(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    cli = _load_visual_cli()
    monkeypatch.setattr(
        cli.visual_artifacts,
        "archive_visuals",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("runtime failure")),
    )

    code = cli.main(
        [
            "archive",
            str(SESSIONS / "visual-embedded-image.jsonl"),
            "--archive-root",
            str(tmp_path),
            "--project-name",
            "Visual Project",
            "--artifact-set",
            "error set",
            "--visual-context",
            "reference",
            "--json",
        ]
    )
    output = capsys.readouterr()

    assert code == 1
    assert output.err.strip() == "error: runtime failure"
    assert "Traceback" not in output.err


def test_verify_legacy_visual_manifest_uses_re_rooted_relative_path(tmp_path: Path) -> None:
    (tmp_path / "legacy-root").mkdir()
    archived = run_visual(
        "archive",
        str(SESSIONS / "visual-embedded-image.jsonl"),
        "--archive-root",
        str(tmp_path / "legacy-root"),
        "--project-name",
        "Visual Project",
        "--artifact-set",
        "legacy set",
        "--visual-context",
        "reference",
        "--json",
    )
    manifest_path = Path(json.loads(archived.stdout)["manifest_json"])
    original_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    original_manifest_parent = manifest_path.parent
    original_archive_dir = original_payload["archive_dir"]
    moved_manifest_parent = tmp_path / "moved-manifest"
    shutil.move(str(original_manifest_parent), str(moved_manifest_parent))

    moved_manifest_path = moved_manifest_parent / manifest_path.name
    moved_payload = json.loads(moved_manifest_path.read_text(encoding="utf-8"))
    for artifact in moved_payload.get("artifacts", []):
        artifact.pop("archive_relative_path", None)
    moved_payload["archive_dir"] = original_archive_dir
    moved_manifest_path.write_text(json.dumps(moved_payload, indent=2) + "\n", encoding="utf-8")

    verified = visual_artifacts.verify_manifest(moved_manifest_path)

    assert verified["status"] == "ok"
    assert verified["checked_files"] == 1
    assert verified["missing_files"] == 0
    assert verified["mismatched_files"] == 0


def test_verify_fails_outside_legacy_archive_path_for_copied_entry(tmp_path: Path) -> None:
    archived = run_visual(
        "archive",
        str(SESSIONS / "visual-embedded-image.jsonl"),
        "--archive-root",
        str(tmp_path),
        "--project-name",
        "Visual Project",
        "--artifact-set",
        "legacy outside set",
        "--visual-context",
        "reference",
        "--json",
    )
    manifest_path = Path(json.loads(archived.stdout)["manifest_json"])
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for artifact in payload.get("artifacts", []):
        if artifact.get("status") == "copied":
            artifact["archive_path"] = str(tmp_path / "outside.jsonl")
            artifact["archive_relative_path"] = None
            break
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    result = visual_artifacts.verify_manifest(manifest_path)

    assert result["status"] == "warn"
    assert result["missing_files"] == 1
    assert result["details"][0]["error"] == "missing archive path metadata"


def test_verify_rejects_copied_artifact_with_invalid_manifest_hash_and_size(tmp_path: Path) -> None:
    archived = run_visual(
        "archive",
        str(SESSIONS / "visual-embedded-image.jsonl"),
        "--archive-root",
        str(tmp_path),
        "--project-name",
        "Visual Project",
        "--artifact-set",
        "hash size set",
        "--visual-context",
        "reference",
        "--json",
    )
    manifest_path = Path(json.loads(archived.stdout)["manifest_json"])
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for artifact in payload.get("artifacts", []):
        if artifact.get("status") == "copied":
            artifact["sha256"] = ""
            artifact["bytes"] = -1
            break
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    result = visual_artifacts.verify_manifest(manifest_path)

    assert result["status"] == "warn"
    assert result["mismatched_files"] == 1
    assert result["details"][0]["error"] in {
        "archive manifest has invalid hash metadata",
        "archive manifest has invalid byte metadata",
    }


def test_wizard_defaults_to_no_write(tmp_path: Path) -> None:
    result = run_visual(
        "wizard",
        str(SESSIONS / "visual-embedded-image.jsonl"),
        input_text=f"{tmp_path}\nVisual Project\nwizard set\nreference\n\nn\n",
    )

    assert result.returncode == 0, result.stderr
    assert "No archive written" in result.stdout
    assert not any(tmp_path.iterdir())


def test_visual_metrics_do_not_backtrack_on_slash_heavy_text() -> None:
    record = {
        "type": "response_item",
        "payload": {
            "type": "message",
            "content": [
                {
                    "type": "text",
                    "text": "/not/a/media/path " * 5000,
                }
            ],
        },
    }

    started = perf_counter()
    metrics = scan_record_visual_metrics(record)

    assert perf_counter() - started < 0.5
    assert metrics["visual_artifacts"] == 0


def test_visual_archive_slug_preserves_expected_output() -> None:
    assert visual_artifacts.visual_archive_slug("My Project") == "my-project"
    assert (
        visual_artifacts.visual_archive_slug("Project.Name_v1") == "project-name-v1"
    )


def _snapshot_archive_bytes(root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _assert_no_staging_or_backup_siblings(archive_root: Path) -> None:
    staging_root = archive_root.parent
    if not staging_root.exists():
        return
    for path in staging_root.iterdir():
        assert not path.name.startswith(".codex-thread-tools-staging-")
        assert not path.name.startswith(".codex-thread-tools-backup-")


def _archive_visuals_success(
    *,
    session: Path,
    archive_root: Path,
    project: str,
    artifact_set: str,
    visual_context: str,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, str]:
    return visual_artifacts.archive_visuals(
        session_file=session,
        archive_root=archive_root,
        project_name=project,
        artifact_set=artifact_set,
        visual_context=visual_context,
        force=force,
        dry_run=dry_run,
        allow_local_roots=[ASSETS],
    )


def test_archive_visuals_dry_run_is_side_effect_free(tmp_path: Path) -> None:
    payload = _archive_visuals_success(
        session=SESSIONS / "visual-markdown-paths.jsonl",
        archive_root=tmp_path,
        project="Visual Project",
        artifact_set="dry run set",
        visual_context="reference",
        dry_run=True,
    )

    assert payload["dry_run"] is True
    assert not (tmp_path / "codex-visual-artifacts").exists()
    assert not any(
        path.name.startswith(".codex-thread-tools-staging-")
        for path in tmp_path.rglob("*")
    )
    assert not any(
        path.name.startswith(".codex-thread-tools-backup-")
        for path in tmp_path.rglob("*")
    )


def test_archive_visuals_force_replacement_removes_stale_artifacts(tmp_path: Path) -> None:
    first = _archive_visuals_success(
        session=SESSIONS / "visual-local-images-event.jsonl",
        archive_root=tmp_path,
        project="Visual Project",
        artifact_set="stale set",
        visual_context="reference",
    )

    archive_dir = Path(first["archive_dir"])
    stale_file = archive_dir / "artifacts" / "stale.bin"
    stale_file.write_text("stale", encoding="utf-8")
    assert stale_file.exists()

    second = _archive_visuals_success(
        session=SESSIONS / "visual-local-images-event.jsonl",
        archive_root=tmp_path,
        project="Visual Project",
        artifact_set="stale set",
        visual_context="reference",
        force=True,
    )

    assert not stale_file.exists()
    assert second["archive_dir"] == first["archive_dir"]
    manifest = json.loads(Path(second["manifest_json"]).read_text(encoding="utf-8"))
    manifest_markdown = Path(second["manifest_markdown"]).read_text(encoding="utf-8")
    handoff_snippet = Path(second["handoff_snippet"]).read_text(encoding="utf-8")
    assert manifest["archive_dir"] == second["archive_dir"]
    assert str(archive_dir / "manifest.json") == second["manifest_json"]
    for key in ("manifest_json", "manifest_markdown", "handoff_snippet", "archive_dir"):
        assert ".codex-thread-tools-staging-" not in second[key]
        assert ".codex-thread-tools-backup-" not in second[key]
        assert second[key].startswith(second["archive_dir"])
    assert f"Archive directory: `{second['archive_dir']}`" in manifest_markdown
    assert f"Visual archive manifest: `{second['archive_dir']}/manifest.md`" in handoff_snippet
    assert f"Archive JSON: `{second['archive_dir']}/manifest.json`" in handoff_snippet
    for value in (manifest_markdown, handoff_snippet):
        assert ".codex-thread-tools-staging-" not in value
        assert ".codex-thread-tools-backup-" not in value

    verify = visual_artifacts.verify_manifest(Path(second["manifest_json"]))
    assert verify["status"] == "ok"

    for artifact in manifest["artifacts"]:
        if artifact["archive_path"]:
            assert artifact["archive_path"].startswith(second["archive_dir"])

    _assert_no_staging_or_backup_siblings(archive_dir)


def test_archive_visuals_fails_and_preserves_existing_archive_if_staged_copy_is_mutated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first = _archive_visuals_success(
        session=SESSIONS / "visual-local-images-event.jsonl",
        archive_root=tmp_path,
        project="Visual Project",
        artifact_set="staged mutation set",
        visual_context="reference",
    )
    archive_dir = Path(first["archive_dir"])
    manifest_path = Path(first["manifest_json"])
    manifest = Path(manifest_path).read_text(encoding="utf-8")

    original_copy = visual_artifacts.atomic_copy_file

    def mutate_staged_copy(source: Path, target: Path) -> None:
        original_copy(source, target)
        target.write_bytes(target.read_bytes() + b"mutated")

    monkeypatch.setattr(visual_artifacts, "atomic_copy_file", mutate_staged_copy)

    with pytest.raises(RuntimeError, match="artifact .* changed while staging"):
        _archive_visuals_success(
            session=SESSIONS / "visual-local-images-event.jsonl",
            archive_root=tmp_path,
            project="Visual Project",
            artifact_set="staged mutation set",
            visual_context="reference",
            force=True,
        )

    assert manifest_path.read_text(encoding="utf-8") == manifest
    _assert_no_staging_or_backup_siblings(archive_dir)


def test_archive_visuals_refuses_symlinked_archive_container(
    tmp_path: Path,
) -> None:
    external_root = tmp_path / "external-container"
    external_root.mkdir()
    sentinel = external_root / "sentinel.txt"
    sentinel.write_text("external", encoding="utf-8")
    container_path = tmp_path / "codex-visual-artifacts"
    container_path.symlink_to(external_root, target_is_directory=True)

    with pytest.raises(SystemExit) as exc:
        _archive_visuals_success(
            session=SESSIONS / "visual-embedded-image.jsonl",
            archive_root=tmp_path,
            project="Visual Project",
            artifact_set="linked set",
            visual_context="reference",
        )

    assert "symlink" in str(exc.value).lower()
    assert sentinel.read_text(encoding="utf-8") == "external"


def test_archive_visuals_refuses_symlinked_archive_project_directory(
    tmp_path: Path,
) -> None:
    container = tmp_path / "codex-visual-artifacts"
    container.mkdir()
    external_project = tmp_path / "external-project"
    external_project.mkdir()
    sentinel = external_project / "sentinel.txt"
    sentinel.write_text("external", encoding="utf-8")
    project_dir = container / "visual-project"
    project_dir.symlink_to(external_project, target_is_directory=True)

    with pytest.raises(SystemExit) as exc:
        _archive_visuals_success(
            session=SESSIONS / "visual-embedded-image.jsonl",
            archive_root=tmp_path,
            project="Visual Project",
            artifact_set="linked set",
            visual_context="reference",
        )

    assert "symlink" in str(exc.value).lower()
    assert sentinel.read_text(encoding="utf-8") == "external"


def test_archive_visuals_rolls_back_on_artifact_copy_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _archive_visuals_success(
        session=SESSIONS / "visual-local-images-event.jsonl",
        archive_root=tmp_path,
        project="Visual Project",
        artifact_set="rollback copy set",
        visual_context="reference",
    )
    archive_dir = Path(baseline["archive_dir"])
    before = _snapshot_archive_bytes(archive_dir)

    def fail_copy(_source: Path, _target: Path) -> None:
        raise RuntimeError("copy failure")

    monkeypatch.setattr(visual_artifacts, "atomic_copy_file", fail_copy)

    try:
        _archive_visuals_success(
            session=SESSIONS / "visual-local-images-event.jsonl",
            archive_root=tmp_path,
            project="Visual Project",
            artifact_set="rollback copy set",
            visual_context="reference",
            force=True,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("artifact copy failure did not propagate")

    assert _snapshot_archive_bytes(archive_dir) == before
    _assert_no_staging_or_backup_siblings(archive_dir)


def test_archive_visuals_rolls_back_on_manifest_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _archive_visuals_success(
        session=SESSIONS / "visual-local-images-event.jsonl",
        archive_root=tmp_path,
        project="Visual Project",
        artifact_set="rollback manifest set",
        visual_context="reference",
    )
    archive_dir = Path(baseline["archive_dir"])
    before = _snapshot_archive_bytes(archive_dir)
    original_write = visual_artifacts.atomic_write_text

    def fail_manifest_write(path: Path, text: str) -> None:
        if path.name == "manifest.md":
            raise RuntimeError("manifest failure")
        original_write(path, text)

    monkeypatch.setattr(visual_artifacts, "atomic_write_text", fail_manifest_write)

    try:
        _archive_visuals_success(
            session=SESSIONS / "visual-local-images-event.jsonl",
            archive_root=tmp_path,
            project="Visual Project",
            artifact_set="rollback manifest set",
            visual_context="reference",
            force=True,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("manifest write failure did not propagate")

    assert _snapshot_archive_bytes(archive_dir) == before
    _assert_no_staging_or_backup_siblings(archive_dir)


def test_archive_visuals_and_session_archives_use_shared_staged_directory() -> None:
    from codex_thread_tools import session_archive

    assert visual_artifacts.staged_directory is session_archive.staged_directory
