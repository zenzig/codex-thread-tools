from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_recovery_module():
    spec = spec_from_file_location(
        "recover_codex_thread_starter_test",
        ROOT / "tools" / "recover-codex-thread-starter.py",
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_recovery(
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "recover-codex-thread-starter.py"), *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_session(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records)
        + "\n",
        encoding="utf-8",
    )


def session_meta() -> dict:
    return {
        "timestamp": "2026-07-18T12:00:00Z",
        "type": "session_meta",
        "payload": {"id": "recovery-session", "cwd": "/work/recovery"},
    }


def invalid_image_message() -> dict:
    return {
        "timestamp": "2026-07-18T12:01:00Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64,this-is-not-valid",
                }
            ],
        },
    }


def test_diagnose_json_reports_redacted_integrity_danger(tmp_path: Path) -> None:
    session = tmp_path / "danger.jsonl"
    write_session(session, [session_meta(), invalid_image_message()])

    result = run_recovery("diagnose", str(session), "--json")

    assert result.returncode == 3, result.stderr
    payload = json.loads(result.stdout)
    rendered = json.dumps(payload)
    assert payload["report_type"] == "codex_session_integrity_diagnosis"
    assert payload["status"] == "danger"
    assert payload["recommended_action"] == "create-recovery-bundle"
    assert payload["integrity"]["invalid_image_urls"] == 1
    assert payload["integrity"]["remote_image_urls"] == 0
    assert payload["integrity"]["findings"] == [
        {
            "kind": "input_image",
            "line": 2,
            "compacted": False,
            "code": "invalid_data_url",
        }
    ]
    assert "this-is-not-valid" not in rendered
    assert "data:image" not in rendered


def test_diagnose_human_output_is_read_only_and_actionable(tmp_path: Path) -> None:
    session = tmp_path / "danger.jsonl"
    write_session(session, [session_meta(), invalid_image_message()])
    before = sorted(path.name for path in tmp_path.iterdir())

    result = run_recovery("diagnose", str(session))

    assert result.returncode == 3, result.stderr
    assert "Codex Session Integrity Diagnosis" in result.stdout
    assert "Status: DANGER" in result.stdout
    assert "Recommended action: create-recovery-bundle" in result.stdout
    assert "data:image" not in result.stdout
    assert sorted(path.name for path in tmp_path.iterdir()) == before


def test_diagnose_returns_caution_for_incomplete_turn_without_bad_image(
    tmp_path: Path,
) -> None:
    session = tmp_path / "incomplete.jsonl"
    write_session(
        session,
        [
            session_meta(),
            {
                "timestamp": "2026-07-18T12:01:00Z",
                "type": "event_msg",
                "payload": {"type": "turn_started", "message": "work started"},
            },
        ],
    )

    result = run_recovery("diagnose", str(session), "--json")

    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "caution"
    assert payload["integrity"]["findings"] == []
    assert payload["pre_handoff_safety"]["incomplete_turn_events"] == 1


def test_diagnose_limits_retained_findings_but_preserves_total_counts(
    tmp_path: Path,
) -> None:
    session = tmp_path / "many-findings.jsonl"
    write_session(
        session,
        [session_meta(), invalid_image_message(), invalid_image_message(), invalid_image_message()],
    )

    result = run_recovery("diagnose", str(session), "--json", "--max-findings", "1")

    assert result.returncode == 3, result.stderr
    payload = json.loads(result.stdout)
    assert payload["integrity"]["invalid_image_urls"] == 3
    assert len(payload["integrity"]["findings"]) == 1


def test_diagnose_reports_bad_cli_input_without_writing(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jsonl"

    result = run_recovery("diagnose", str(missing), "--json")

    assert result.returncode == 1
    assert result.stdout == ""
    assert "session file does not exist" in result.stderr


def test_bundle_creates_redacted_external_recovery_artifact(tmp_path: Path) -> None:
    session = tmp_path / "danger.jsonl"
    project_root = tmp_path / "project"
    output_root = tmp_path / "bundles"
    project_root.mkdir()
    secret = "sk-" + "very-secret-test-token-1234567890"
    tool_payload = "RAW_TOOL_PAYLOAD_DO_NOT_COPY"
    write_session(
        session,
        [
            session_meta(),
            {
                "timestamp": "2026-07-18T12:00:30Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Durable fact: deploy to staging. API key " + secret,
                        }
                    ],
                },
            },
            {
                "timestamp": "2026-07-18T12:00:45Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": tool_payload,
                },
            },
            invalid_image_message(),
        ],
    )
    before = session.read_bytes()

    result = run_recovery(
        "bundle",
        str(session),
        "--project-root",
        str(project_root),
        "--output-root",
        str(output_root),
    )

    assert result.returncode == 0, result.stderr
    bundle_dirs = [path for path in output_root.iterdir() if path.is_dir()]
    assert len(bundle_dirs) == 1
    bundle = bundle_dirs[0]
    assert result.stdout == f"bundle: {bundle}\n"
    assert {path.name for path in bundle.iterdir()} == {
        "integrity-report.json",
        "recovery.md",
        "handoff-template.md",
        "fresh-task-prompt.md",
        "visual-decision.md",
        "manifest.json",
    }
    report = json.loads((bundle / "integrity-report.json").read_text(encoding="utf-8"))
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert report["integrity"]["invalid_image_urls"] == 1
    assert report["source"]["sha256"]
    assert report["source"]["file"] == str(session)
    assert manifest["type"] == "codex_session_recovery_bundle"
    assert manifest["source"]["file"] == str(session)
    assert set(manifest["files"]) == {
        "integrity-report.json",
        "recovery.md",
        "handoff-template.md",
        "fresh-task-prompt.md",
        "visual-decision.md",
        "manifest.json",
    }
    assert "artifacts" in manifest
    assert set(manifest["artifacts"].keys()) == {
        "integrity-report.json",
        "recovery.md",
        "handoff-template.md",
        "fresh-task-prompt.md",
        "visual-decision.md",
    }
    for name, artifact in manifest["artifacts"].items():
        assert artifact["sha256"]
        assert artifact["bytes"] > 0
        assert "staging" not in artifact["path"]
        artifact_path = bundle / name
        assert artifact["sha256"] == sha256(artifact_path.read_bytes()).hexdigest()
        assert artifact["bytes"] == artifact_path.stat().st_size
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in bundle.iterdir())
    assert "Durable fact: deploy to staging." in rendered
    assert secret not in rendered
    assert tool_payload not in rendered
    assert "data:image" not in rendered
    assert session.read_bytes() == before


def test_bundle_rejects_output_inside_live_session_tree(tmp_path: Path) -> None:
    home = tmp_path / "home"
    session_root = home / ".codex" / "sessions"
    session = session_root / "2026" / "07" / "18" / "danger.jsonl"
    session.parent.mkdir(parents=True)
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_session(session, [session_meta(), invalid_image_message()])
    env = {**os.environ, "HOME": str(home)}

    result = run_recovery(
        "bundle",
        str(session),
        "--project-root",
        str(project_root),
        "--output-root",
        str(session_root),
        env=env,
    )

    assert result.returncode == 1
    assert "outside the live Codex session tree" in result.stderr
    assert list(session_root.rglob("*.jsonl")) == [session]


def test_bundle_requires_a_project_directory(tmp_path: Path) -> None:
    session = tmp_path / "danger.jsonl"
    output_root = tmp_path / "bundles"
    project_file = tmp_path / "not-a-project"
    project_file.write_text("not a directory", encoding="utf-8")
    write_session(session, [session_meta(), invalid_image_message()])

    result = run_recovery(
        "bundle",
        str(session),
        "--project-root",
        str(project_file),
        "--output-root",
        str(output_root),
    )

    assert result.returncode == 1
    assert "project root is not a directory" in result.stderr
    assert not output_root.exists()


def test_bundle_redacts_data_urls_case_insensitively(tmp_path: Path) -> None:
    session = tmp_path / "danger.jsonl"
    project_root = tmp_path / "project"
    output_root = tmp_path / "bundles"
    project_root.mkdir()
    uppercase_data_url = "DATA:IMAGE/PNG;base64,LEAKED_IMAGE_BYTES"
    write_session(
        session,
        [
            session_meta(),
            {
                "timestamp": "2026-07-18T12:00:30Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Context note: " + uppercase_data_url,
                        }
                    ],
                },
            },
            invalid_image_message(),
        ],
    )

    result = run_recovery(
        "bundle",
        str(session),
        "--project-root",
        str(project_root),
        "--output-root",
        str(output_root),
    )

    assert result.returncode == 0, result.stderr
    rendered = "\n".join(
        path.read_text(encoding="utf-8")
        for path in next(path for path in output_root.iterdir() if path.is_dir()).iterdir()
    )
    assert uppercase_data_url not in rendered
    assert "LEAKED_IMAGE_BYTES" not in rendered


def test_bundle_source_change_before_publish_removes_staging(tmp_path: Path, monkeypatch) -> None:
    module = load_recovery_module()
    session = tmp_path / "danger.jsonl"
    project_root = tmp_path / "project"
    output_root = tmp_path / "bundles"
    project_root.mkdir()
    write_session(session, [session_meta(), invalid_image_message()])
    original_staged_directory = module.staged_directory

    @contextmanager
    def mutate_before_publish(*args, **kwargs):
        before_publish = kwargs["before_publish"]

        def mutate_then_verify() -> None:
            session.write_text("{}\n", encoding="utf-8")
            before_publish()

        kwargs["before_publish"] = mutate_then_verify
        with original_staged_directory(*args, **kwargs) as staging_dir:
            yield staging_dir

    monkeypatch.setattr(module, "staged_directory", mutate_before_publish)
    args = SimpleNamespace(
        session_file=str(session),
        project_root=str(project_root),
        output_root=str(output_root),
        force=False,
    )

    with pytest.raises(SystemExit, match="session source changed during bundle creation"):
        module.run_bundle(args)

    assert not [path for path in output_root.glob("*") if path.is_dir()]


def test_bundle_rejects_output_root_symlink_swap_before_staging(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_recovery_module()
    session = tmp_path / "danger.jsonl"
    project_root = tmp_path / "project"
    output_root = tmp_path / "bundles"
    live_root = tmp_path / "live-sessions"
    project_root.mkdir()
    output_root.mkdir()
    live_root.mkdir()
    write_session(session, [session_meta(), invalid_image_message()])
    monkeypatch.setattr(module, "default_session_root", lambda: live_root)
    original_staged_directory = module.staged_directory

    @contextmanager
    def swap_before_staging(*args, **kwargs):
        before_stage = kwargs["before_stage"]

        def swap_then_verify() -> None:
            output_root.rmdir()
            output_root.symlink_to(live_root, target_is_directory=True)
            before_stage()

        kwargs["before_stage"] = swap_then_verify
        with original_staged_directory(*args, **kwargs) as staging_dir:
            yield staging_dir

    monkeypatch.setattr(module, "staged_directory", swap_before_staging)
    args = SimpleNamespace(
        session_file=str(session),
        project_root=str(project_root),
        output_root=str(output_root),
        force=False,
    )

    with pytest.raises(
        SystemExit,
        match="(bundle output root is a symlink|live Codex session tree)",
    ):
        module.run_bundle(args)

    assert not list(live_root.iterdir())


def test_bundle_force_replaces_same_second_destination(tmp_path: Path, monkeypatch) -> None:
    module = load_recovery_module()
    session = tmp_path / "danger.jsonl"
    project_root = tmp_path / "project"
    output_root = tmp_path / "bundles"
    project_root.mkdir()
    write_session(session, [session_meta(), invalid_image_message()])
    monkeypatch.setattr(module, "now_stamp", lambda: "20260718-120000")
    base_args = {
        "session_file": str(session),
        "project_root": str(project_root),
        "output_root": str(output_root),
    }

    assert module.run_bundle(SimpleNamespace(**base_args, force=False)) == 0
    with pytest.raises(ValueError, match="use --force to overwrite"):
        module.run_bundle(SimpleNamespace(**base_args, force=False))
    assert module.run_bundle(SimpleNamespace(**base_args, force=True)) == 0


def test_bundle_defaults_to_thread_tools_recovery_root(tmp_path: Path) -> None:
    home = tmp_path / "home"
    env = {**os.environ, "HOME": str(home)}
    session = tmp_path / "danger.jsonl"
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_session(session, [session_meta(), invalid_image_message()])
    output_root = home / ".codex" / "thread-tools" / "recovery-bundles"

    result = run_recovery(
        "bundle",
        str(session),
        "--project-root",
        str(project_root),
        env=env,
    )

    assert result.returncode == 0, result.stderr
    bundle_dirs = [path for path in output_root.iterdir() if path.is_dir()]
    assert len(bundle_dirs) == 1
