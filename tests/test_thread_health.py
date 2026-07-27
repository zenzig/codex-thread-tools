from __future__ import annotations

import json
import base64
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "sessions"

ACTIVE_TURN_DIAGNOSTIC = (
    "active turn has no terminal completion, abort, or error event"
)
COMPACTED_VISUAL_REFERENCE_DIAGNOSTIC = (
    "visual references exist inside compacted replacement history"
)


def run_health(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "codex-thread-health.py"), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_health_with_env(
    env: dict[str, str],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "codex-thread-health.py"), *args],
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


def assert_json_stdout(result: subprocess.CompletedProcess[str]) -> dict:
    assert "Codex Thread Health" not in result.stdout
    assert "Codex Project Token Usage" not in result.stdout
    return json.loads(result.stdout)


def test_check_reports_structural_image_integrity_danger_signals(tmp_path: Path) -> None:
    session = tmp_path / "integrity-danger.jsonl"
    write_session(
        session,
        [
            {
                "timestamp": "2026-07-18T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "integrity-danger", "cwd": "/work/integrity"},
            },
            {
                "timestamp": "2026-07-18T12:01:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,this-is-not-valid",
                        },
                        {
                            "type": "input_image",
                            "image_url": "https://example.com/model-visible.png",
                        },
                    ],
                },
            },
        ],
    )

    result = run_health("check", str(session), "--json")

    assert result.returncode == 3, result.stderr
    payload = assert_json_stdout(result)
    metrics = payload["metrics"]
    assert metrics["invalid_image_urls"] == 1
    assert metrics["invalid_image_urls_in_compacted_records"] == 0
    assert metrics["remote_image_urls"] == 1
    assert metrics["session_integrity_findings"] == 2
    assert metrics["history_base_present"] is False
    assert payload["risk_domains"]["visuals"]["status"] == "danger"
    assert "invalid model-visible image URL can break thread replay" in payload["reasons"]
    assert "remote model-visible image URL is unsafe for thread replay" in payload["reasons"]


def test_check_distinguishes_invalid_image_inside_compacted_history(tmp_path: Path) -> None:
    session = tmp_path / "integrity-compacted.jsonl"
    write_session(
        session,
        [
            {
                "timestamp": "2026-07-18T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "integrity-compacted", "cwd": "/work/integrity"},
            },
            {
                "timestamp": "2026-07-18T12:01:00Z",
                "type": "compacted",
                "payload": {
                    "replacement_history": [
                        {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_image",
                                    "image_url": "data:image/png;base64,this-is-not-valid",
                                }
                            ],
                        }
                    ]
                },
            },
        ],
    )

    result = run_health("check", str(session), "--json")

    assert result.returncode == 3, result.stderr
    payload = assert_json_stdout(result)
    assert payload["metrics"]["invalid_image_urls"] == 1
    assert payload["metrics"]["invalid_image_urls_in_compacted_records"] == 1
    assert (
        "invalid model-visible image URL exists inside compacted replacement history"
        in payload["reasons"]
    )


def test_check_reports_history_base_as_additive_metadata(tmp_path: Path) -> None:
    session = tmp_path / "history-base.jsonl"
    write_session(
        session,
        [
            {
                "timestamp": "2026-07-18T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "history-base", "cwd": "/work/integrity"},
                "history_base": "parent-thread-id",
            }
        ],
    )

    result = run_health("check", str(session), "--json")

    assert result.returncode == 0, result.stderr
    payload = assert_json_stdout(result)
    assert payload["metrics"]["history_base_present"] is True


def test_health_streams_integrity_without_file_level_rescan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from codex_thread_tools import thread_health
    from codex_thread_tools.session_integrity import SessionIntegrityAccumulator

    session = tmp_path / "streamed-integrity.jsonl"
    write_session(
        session,
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,not-valid",
                        },
                        {
                            "type": "input_image",
                            "image_url": "https://example.com/image.png",
                        },
                    ],
                },
            }
        ],
    )
    observed_max_findings: list[int] = []

    class ObservedAccumulator(SessionIntegrityAccumulator):
        def __init__(self, *, max_findings: int) -> None:
            observed_max_findings.append(max_findings)
            super().__init__(max_findings=max_findings)

    def fail_file_level_scan(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("health must not rescan the JSONL file")

    monkeypatch.setattr(
        thread_health,
        "scan_session_integrity",
        fail_file_level_scan,
        raising=False,
    )
    monkeypatch.setattr(
        thread_health,
        "SessionIntegrityAccumulator",
        ObservedAccumulator,
        raising=False,
    )

    payload = thread_health.analyze_session_file(session, thread_health.HealthThresholds())

    assert observed_max_findings == [0]
    assert payload["status"] == "danger"
    assert payload["metrics"]["invalid_image_urls"] == 1
    assert payload["metrics"]["remote_image_urls"] == 1
    assert payload["metrics"]["session_integrity_findings"] == 2
    assert payload["risk_domains"]["visuals"]["status"] == "danger"


def test_remote_help_exposes_connection_and_report_options() -> None:
    result = run_health("remote", "--help")

    assert result.returncode == 0
    for option in (
        "--host",
        "--project",
        "--connect-timeout",
        "--mode",
        "--size-format",
        "--json",
    ):
        assert option in result.stdout
    assert "--progress" not in result.stdout
    assert "--handoff-marker-file" not in result.stdout


@pytest.mark.parametrize("command", ["check", "projects", "tokens"])
def test_local_health_help_preserves_scan_options(command: str) -> None:
    result = run_health(command, "--help")

    assert result.returncode == 0
    assert "--progress" in result.stdout
    assert "--handoff-marker-file" in result.stdout


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--progress", "never"),
        ("--handoff-marker-file", "/local/markers.jsonl"),
    ],
)
def test_remote_rejects_local_scan_options(option: str, value: str) -> None:
    result = run_health(
        "remote",
        "--host=-unsafe-host",
        option,
        value,
    )

    assert result.returncode == 2
    assert f"unrecognized arguments: {option} {value}" in result.stderr


def test_remote_requires_host() -> None:
    result = run_health("remote")

    assert result.returncode == 2
    assert "the following arguments are required: --host" in result.stderr


def remote_projects_report(*statuses: str) -> dict:
    projects = [
        {
            "project": f"/home/rich/project-{index}",
            "file": f"/remote/.codex/sessions/project-{index}.jsonl",
            "status": status,
            "continuation_status": status,
            "recommendation": "handoff-now" if status == "danger" else "continue",
            "metrics": {
                "bytes": 1024,
                "response_items": 10,
                "compacted_records": 0,
                "visual_artifacts": 0,
            },
            "reasons": [],
            "risk_domains": {
                name: {"status": "ok", "evidence": []}
                for name in ("load", "visuals", "compaction", "limits", "continuity")
            },
            "handoff_readiness": {"status": "not-needed"},
            "handoff_summary": {
                "total_handoffs": 0,
                "latest_handoff_at": "",
            },
            "replaces_session_ids": [],
            "retired_by_handoff": False,
        }
        for index, status in enumerate(statuses, 1)
    ]
    return {
        "remote_health_protocol": 1,
        "session_root": "/remote/.codex/sessions",
        "summary": {
            "projects": len(projects),
            "ok": sum(item["status"] == "ok" for item in projects),
            "warn": sum(item["status"] == "warn" for item in projects),
            "danger": sum(item["status"] == "danger" for item in projects),
            "retired": sum(item["status"] == "retired" for item in projects),
        },
        "projects": projects,
    }


def fake_ssh_env(tmp_path: Path, report: dict) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    record_file = tmp_path / "ssh-arguments.jsonl"
    ssh = fake_bin / "ssh"
    ssh.write_text(
        """#!/usr/bin/env python3
import json
import os
import shlex
import sys

arguments = sys.argv[1:]
with open(os.environ[\"FAKE_SSH_RECORD\"], \"a\", encoding=\"utf-8\") as handle:
    handle.write(json.dumps(arguments) + \"\\n\")
command = arguments[-1]
command_parts = shlex.split(command)
if command_parts[:2] == [\"sh\", \"-c\"]:
    command_parts = shlex.split(command_parts[-1])
if command_parts == [\"codex-thread-tools\", \"--version\"]:
    print(os.environ.get(\"FAKE_SSH_VERSION\", \"1.0.0\"))
    print(os.environ.get(\"FAKE_SSH_VERSION_STDERR\", \"\"), file=sys.stderr)
    raise SystemExit(int(os.environ.get(\"FAKE_SSH_VERSION_EXIT\", \"0\")))
print(os.environ[\"FAKE_SSH_REPORT\"])
print(os.environ.get(\"FAKE_SSH_HEALTH_STDERR\", \"\"), file=sys.stderr)
raise SystemExit(int(os.environ.get(\"FAKE_SSH_HEALTH_EXIT\", \"0\")))
""",
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "FAKE_SSH_RECORD": str(record_file),
            "FAKE_SSH_REPORT": json.dumps(report),
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
        }
    )
    return env


def fake_ssh_commands(env: dict[str, str]) -> list[list[str]]:
    return [
        json.loads(line)
        for line in Path(env["FAKE_SSH_RECORD"]).read_text(encoding="utf-8").splitlines()
    ]


def test_remote_json_adds_metadata_and_filters_project(tmp_path: Path) -> None:
    report = remote_projects_report("ok", "danger")
    report["projects"][0]["project"] = "/home/rich/atomic-development"
    env = fake_ssh_env(tmp_path, report)

    result = run_health_with_env(
        env,
        "remote",
        "--host",
        "node1.atomicfalls.com",
        "--project",
        "/home/rich/atomic-development",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["source"] == "remote"
    assert payload["host"] == "node1.atomicfalls.com"
    assert [item["project"] for item in payload["projects"]] == [
        "/home/rich/atomic-development"
    ]


def test_remote_pretty_identifies_source_and_host(tmp_path: Path) -> None:
    env = fake_ssh_env(tmp_path, remote_projects_report("ok"))

    result = run_health_with_env(
        env,
        "remote",
        "--host",
        "node1.atomicfalls.com",
        "--mode",
        "compact",
    )

    assert result.returncode == 0, result.stderr
    assert "Source: REMOTE" in result.stdout
    assert "Host: node1.atomicfalls.com" in result.stdout


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("compact", "Project Summary"),
        ("standard", "Action Summary"),
        ("verbose", "Attention Required"),
    ],
)
def test_remote_pretty_modes_render_safe_report_schema(
    tmp_path: Path,
    mode: str,
    expected: str,
) -> None:
    env = fake_ssh_env(tmp_path, remote_projects_report("warn"))

    result = run_health_with_env(
        env,
        "remote",
        "--host",
        "node1.atomicfalls.com",
        "--mode",
        mode,
    )

    assert result.returncode == 2, result.stderr
    assert "Source: REMOTE" in result.stdout
    assert expected in result.stdout


def test_remote_forwards_explicit_thresholds_only(tmp_path: Path) -> None:
    report = remote_projects_report("ok")
    report["projects"][0]["project"] = "/home/rich/atomic-development"
    env = fake_ssh_env(tmp_path, report)

    result = run_health_with_env(
        env,
        "remote",
        "--host",
        "node1.atomicfalls.com",
        "--project",
        "/home/rich/atomic-development",
        "--warn-bytes",
        "101",
        "--danger-bytes",
        "202",
        "--warn-items",
        "3",
        "--danger-items",
        "4",
        "--max-healthy-compactions",
        "5",
        "--mode",
        "compact",
        "--size-format",
        "human",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    health_command = shlex.split(fake_ssh_commands(env)[1][-1])
    assert health_command == [
        "codex-thread-tools",
        "health",
        "projects",
        "--warn-bytes",
        "101",
        "--danger-bytes",
        "202",
        "--warn-items",
        "3",
        "--danger-items",
        "4",
        "--max-healthy-compactions",
        "5",
        "--remote-safe-json",
        "--progress",
        "never",
    ]


def test_remote_version_warning_preserves_json_stdout(tmp_path: Path) -> None:
    env = fake_ssh_env(tmp_path, remote_projects_report("ok"))
    env["FAKE_SSH_VERSION"] = "1.0.1"

    result = run_health_with_env(
        env,
        "remote",
        "--host",
        "node1.atomicfalls.com",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["source"] == "remote"
    local_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert (
        f"Warning: remote version differs: local {local_version}, remote 1.0.1"
        in result.stderr
    )


def test_remote_health_errors_return_one_with_empty_stdout(tmp_path: Path) -> None:
    env = fake_ssh_env(tmp_path, remote_projects_report("ok"))
    env["FAKE_SSH_HEALTH_EXIT"] = "255"
    env["FAKE_SSH_HEALTH_STDERR"] = "Connection refused"

    result = run_health_with_env(
        env,
        "remote",
        "--host",
        "node1.atomicfalls.com",
        "--json",
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "error: SSH command failed for node1.atomicfalls.com: Connection refused" in result.stderr


def test_remote_danger_with_zeroed_summary_is_protocol_error(tmp_path: Path) -> None:
    report = remote_projects_report("danger")
    report["summary"] = {
        "projects": 0,
        "ok": 0,
        "warn": 0,
        "danger": 0,
        "retired": 0,
    }
    env = fake_ssh_env(tmp_path, report)

    result = run_health_with_env(
        env,
        "remote",
        "--host",
        "node1.atomicfalls.com",
        "--json",
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "summary does not match projects" in result.stderr


@pytest.mark.parametrize(
    ("env_overrides", "args", "expected"),
    [
        (
            {
                "FAKE_SSH_VERSION_EXIT": "255",
                "FAKE_SSH_VERSION_STDERR": "Permission denied (publickey)",
            },
            (),
            "SSH command failed for node1.atomicfalls.com: Permission denied (publickey)",
        ),
        (
            {"FAKE_SSH_VERSION_EXIT": "127"},
            (),
            "not installed or not available to non-interactive SSH",
        ),
        (
            {"FAKE_SSH_VERSION": "2.0.0"},
            (),
            "incompatible remote version",
        ),
        (
            {"FAKE_SSH_REPORT": "{truncated: remote-stdout-sentinel}"},
            (),
            "returned malformed JSON",
        ),
        (
            {
                "FAKE_SSH_REPORT": json.dumps(
                    {
                        "remote_health_protocol": 1,
                        "session_root": "/remote/.codex/sessions",
                        "summary": {"projects": 0, "ok": 0, "warn": 0, "danger": 0, "retired": 0},
                    }
                )
            },
            (),
            "invalid remote health report",
        ),
        (
            {},
            ("--project", "/home/rich/missing"),
            "remote project was not found",
        ),
        (
            {},
            ("--connect-timeout", "0"),
            "timeout must be at least 1 second",
        ),
    ],
)
def test_remote_operational_failures_keep_stdout_empty(
    tmp_path: Path,
    env_overrides: dict[str, str],
    args: tuple[str, ...],
    expected: str,
) -> None:
    env = fake_ssh_env(tmp_path, remote_projects_report("ok"))
    env.update(env_overrides)

    result = run_health_with_env(
        env,
        "remote",
        "--host",
        "node1.atomicfalls.com",
        "--json",
        *args,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert expected in result.stderr
    assert "remote-stdout-sentinel" not in result.stderr


def test_remote_rejects_unsafe_host_and_project_stays_local(
    tmp_path: Path,
) -> None:
    host_sentinel = Path("/tmp/host-injection")
    project_sentinel = Path("/tmp/project-injection")
    host_sentinel.unlink(missing_ok=True)
    project_sentinel.unlink(missing_ok=True)
    malicious_host = "node1.atomicfalls.com;touch /tmp/host-injection"
    malicious_project = "/home/rich/atomic-development;touch /tmp/project-injection"
    report = remote_projects_report("ok")
    report["projects"][0]["project"] = malicious_project
    env = fake_ssh_env(tmp_path, report)

    result = run_health_with_env(
        env,
        "remote",
        "--host",
        malicious_host,
        "--project",
        malicious_project,
        "--json",
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "SSH host contains whitespace or control characters" in result.stderr
    assert not host_sentinel.exists()
    assert not project_sentinel.exists()
    assert not Path(env["FAKE_SSH_RECORD"]).exists()


def test_remote_rejects_option_like_host_before_ssh_execution(tmp_path: Path) -> None:
    env = fake_ssh_env(tmp_path, remote_projects_report("ok"))

    result = run_health_with_env(
        env,
        "remote",
        "--host=-unsafe-host",
        "--json",
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "SSH host must be a non-empty destination" in result.stderr
    assert not Path(env["FAKE_SSH_RECORD"]).exists()


def test_remote_safe_projects_protocol_never_serializes_raw_session_content(
    tmp_path: Path,
) -> None:
    sentinels = {
        "event": "RAW_EVENT_SENTINEL_7d83",
        "tool": "RAW_TOOL_SENTINEL_4a21",
        "transcript": "RAW_TRANSCRIPT_SENTINEL_91ce",
        "replacement": "raw-marker-shaped-transcript-sentinel",
        "visual": "RAW_VISUAL_SENTINEL_2bf5",
    }
    session_root = tmp_path / "sessions"
    session = session_root / "2026" / "07" / "13" / "privacy.jsonl"
    write_session(
        session,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "privacy-session",
                    "cwd": "/work/privacy-project",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "error",
                    "message": (
                        "context window exhausted " + sentinels["event"]
                    ),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": sentinels["tool"],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": sentinels["transcript"]}
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Codex thread handoff marker:\n"
                                f"source_session_id: {sentinels['replacement']}\n"
                                "handoff_file: /work/private/handoff.md\n"
                                "project: /work/privacy-project\n"
                                "handoff_sequence: 1"
                            ),
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": (
                                "data:image/png;base64," + sentinels["visual"]
                            ),
                        }
                    ],
                },
            },
        ],
    )

    remote_result = run_health(
        "projects",
        "--session-root",
        str(session_root),
        "--safe-test-mode",
        "--remote-safe-json",
        "--progress",
        "never",
    )

    assert remote_result.returncode in {0, 2, 3}, remote_result.stderr
    for sentinel in sentinels.values():
        assert sentinel not in remote_result.stdout
        assert sentinel not in remote_result.stderr
    remote_payload = json.loads(remote_result.stdout)
    assert remote_payload["remote_health_protocol"] == 1
    assert set(remote_payload["projects"][0]["metrics"]) == {
        "bytes",
        "response_items",
        "compacted_records",
        "visual_artifacts",
        "invalid_image_urls",
        "invalid_image_urls_in_compacted_records",
        "remote_image_urls",
        "session_integrity_findings",
    }
    assert remote_payload["projects"][0]["replaces_session_ids"] == []

    local_result = run_health(
        "projects",
        "--session-root",
        str(session_root),
        "--safe-test-mode",
        "--json",
        "--progress",
        "never",
    )
    assert local_result.returncode in {0, 2, 3}, local_result.stderr
    local_payload = json.loads(local_result.stdout)
    assert (
        local_payload["projects"][0]["metrics"]["compaction_failures"]
        == ["compaction failure or context-window error event was recorded"]
    )
    assert local_payload["projects"][0]["replaces_session_ids"] == [
        sentinels["replacement"]
    ]


@pytest.mark.parametrize(
    ("status", "expected_returncode"),
    [("ok", 0), ("warn", 2), ("danger", 3)],
)
def test_remote_project_filter_recomputes_exit_code(
    tmp_path: Path,
    status: str,
    expected_returncode: int,
) -> None:
    report = remote_projects_report(status, "danger")
    report["projects"][0]["project"] = "/home/rich/atomic-development"
    env = fake_ssh_env(tmp_path, report)

    result = run_health_with_env(
        env,
        "remote",
        "--host",
        "node1.atomicfalls.com",
        "--project",
        "/home/rich/atomic-development",
        "--json",
    )

    assert result.returncode == expected_returncode, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"] == {
        "projects": 1,
        "ok": int(status == "ok"),
        "warn": int(status == "warn"),
        "danger": int(status == "danger"),
        "retired": 0,
    }


def write_session(path: Path, records: list[dict], mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )
    if mtime is not None:
        import os

        os.utime(path, (mtime, mtime))


def test_check_healthy_fixture_is_ok() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "healthy.jsonl"),
        "--safe-test-mode",
        "--json",
        "--warn-items",
        "20",
        "--danger-items",
        "40",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["recommendation"] == "continue"
    assert payload["metrics"]["response_items"] == 8
    assert payload["metrics"]["compaction_items"] == 0


def test_check_compaction_success_is_ok_not_handoff() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "compaction-success.jsonl"),
        "--safe-test-mode",
        "--json",
        "--warn-items",
        "20",
        "--danger-items",
        "40",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["recommendation"] == "continue"
    assert payload["metrics"]["compaction_triggers"] == 1
    assert payload["metrics"]["compaction_items"] == 2
    assert payload["metrics"]["compaction_request_items"] == 3
    assert payload["metrics"]["installed_compaction_checkpoints"] == 1
    assert payload["metrics"]["latest_compaction_installed"] is True
    assert payload["metrics"]["latest_compaction_state"] == "installed"
    assert not payload["metrics"]["compaction_failures"]
    assert payload["risk_domains"]["compaction"]["status"] == "ok"
    assert payload["continuation_status"] == "ok"
    assert payload["handoff_readiness"]["status"] == "not-needed"


def test_check_compaction_failure_recommends_handoff() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "compaction-failed.jsonl"),
        "--safe-test-mode",
        "--json",
        "--warn-items",
        "20",
        "--danger-items",
        "40",
    )

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "danger"
    assert payload["recommendation"] == "handoff-now"
    assert payload["metrics"]["compaction_failures"]
    assert any("compaction" in reason for reason in payload["reasons"])
    assert payload["risk_domains"]["compaction"]["status"] == "danger"
    assert payload["risk_domains"]["continuity"]["status"] == "danger"


def test_check_compaction_failure_records_canonical_diagnostic_without_raw_text() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "compaction-failed.jsonl"),
        "--safe-test-mode",
        "--json",
        "--warn-items",
        "20",
        "--danger-items",
        "40",
    )

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    serialized = json.dumps(payload)

    assert payload["metrics"]["compaction_failures"] == [
        "compaction failure or context-window error event was recorded",
        "compaction failure or context-window error event was recorded",
    ]
    assert "maximum length" not in serialized
    assert "remote compaction v2" not in serialized


def test_check_long_thread_warning_records_canonical_diagnostic(tmp_path: Path) -> None:
    private_path = "/tmp/private-workdir/session-event.log"
    sentinel = "RAW_WARNING_SENTINEL_33ab"
    session = tmp_path / "long-thread-warning.jsonl"
    write_session(
        session,
        [
            {
                "timestamp": "2026-05-24T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "long-thread-warning", "cwd": "/work/long-thread"},
            },
            {
                "timestamp": "2026-05-24T12:01:00Z",
                "type": "response_item",
                "payload": {"type": "compaction", "encrypted_content": "payload"},
            },
            {
                "timestamp": "2026-05-24T12:01:00Z",
                "type": "response_item",
                "payload": {"type": "compaction", "encrypted_content": "payload"},
            },
            {
                "timestamp": "2026-05-24T12:01:00Z",
                "type": "response_item",
                "payload": {"type": "compaction", "encrypted_content": "payload"},
            },
            {
                "timestamp": "2026-05-24T12:01:00Z",
                "type": "response_item",
                "payload": {"type": "compaction", "encrypted_content": "payload"},
            },
            {
                "timestamp": "2026-05-24T12:01:00Z",
                "type": "response_item",
                "payload": {"type": "compaction", "encrypted_content": "payload"},
            },
            {
                "timestamp": "2026-05-24T12:01:00Z",
                "type": "response_item",
                "payload": {"type": "compaction", "encrypted_content": "payload"},
            },
            {
                "timestamp": "2026-05-24T12:01:00Z",
                "type": "response_item",
                "payload": {"type": "compaction", "encrypted_content": "payload"},
            },
            {
                "timestamp": "2026-05-24T12:01:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "warning",
                    "message": (
                        f"thread health notice from {private_path}: "
                        f"{sentinel} long threads and multiple compactions "
                        "instructing us to start a new thread now"
                    ),
                },
            },
        ],
        mtime=1.0,
    )

    result = run_health(
        "check",
        str(session),
        "--safe-test-mode",
        "--json",
    )

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    serialized = json.dumps(payload)

    assert payload["metrics"]["long_thread_warnings"] == [
        "long-thread or context-window warning event was recorded",
    ]
    assert private_path not in serialized
    assert sentinel not in serialized


def test_check_many_compactions_warns_about_quality() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "many-compactions.jsonl"),
        "--safe-test-mode",
        "--json",
        "--max-healthy-compactions",
        "3",
    )

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["recommendation"] == "handoff-now"
    assert payload["metrics"]["compaction_items"] == 6
    assert any("multiple compactions" in reason for reason in payload["reasons"])
    assert payload["handoff_readiness"]["status"] == "needed"


def test_opaque_compaction_items_alone_are_not_health_risk(tmp_path: Path) -> None:
    session = tmp_path / "opaque-compaction-items.jsonl"
    records = [
        {
            "timestamp": "2026-05-24T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": "opaque-compactions", "cwd": "/work/opaque"},
        },
        {
            "timestamp": "2026-05-24T12:00:00Z",
            "type": "turn_context",
            "payload": {"cwd": "/work/opaque", "model": "gpt-5.5"},
        },
    ]
    for index in range(6):
        records.append(
            {
                "timestamp": "2026-05-24T12:00:00Z",
                "type": "response_item",
                "payload": {"type": "compaction", "encrypted_content": f"opaque-{index}"},
            }
        )
    records.append(
        {
            "timestamp": "2026-05-24T12:00:00Z",
            "type": "event_msg",
            "payload": {"type": "turn_complete", "message": "turn complete"},
        }
    )
    session.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )

    result = run_health("check", str(session), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["continuation_status"] == "ok"
    assert payload["metrics"]["compaction_request_items"] == 6
    assert payload["metrics"]["installed_compaction_checkpoints"] == 0
    assert payload["metrics"]["latest_compaction_installed"] is False
    assert payload["metrics"]["latest_compaction_state"] == "request-only"
    assert payload["risk_domains"]["compaction"]["status"] == "ok"
    assert payload["handoff_readiness"]["status"] == "not-needed"


def test_projects_uses_latest_session_per_project_without_live_root() -> None:
    result = run_health(
        "projects",
        "--session-root",
        str(FIXTURES),
        "--safe-test-mode",
        "--json",
        "--warn-items",
        "20",
        "--danger-items",
        "40",
    )

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    projects = {entry["project"]: entry for entry in payload["projects"]}
    assert set(projects) == {
        "/work/project-a",
        "/work/project-b",
        "/work/project-c",
        "/work/project-d",
        "/work/project-e",
        "/work/project-f",
        "/work/project-g",
        "/work/project-h",
            "/work/project-i",
            "/work/project-j",
            "/work/project-visual",
        }
    assert payload["summary"]["projects"] == 11
    assert payload["summary"]["warn"] == 1
    assert payload["summary"]["danger"] == 4


def test_projects_reports_root_compactions_instead_of_newer_subagent(
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "sessions"
    project = "/work/thread-family"
    parent = session_root / "parent.jsonl"
    child = session_root / "child.jsonl"
    write_session(
        parent,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "parent",
                    "cwd": project,
                    "thread_source": "user",
                },
            },
            {
                "type": "compacted",
                "payload": {"replacement_history": []},
            },
        ],
        mtime=100,
    )
    write_session(
        child,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "child",
                    "cwd": project,
                    "thread_source": "subagent",
                    "parent_thread_id": "parent",
                },
            }
        ],
        mtime=200,
    )

    result = run_health(
        "projects",
        "--session-root",
        str(session_root),
        "--safe-test-mode",
        "--json",
    )

    payload = json.loads(result.stdout)
    assert payload["projects"][0]["file"] == str(parent)
    assert payload["projects"][0]["metrics"]["compacted_records"] == 1


def test_projects_reports_replacement_thread_when_source_was_handed_off(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    marker_file = tmp_path / "markers" / "handoff-markers.jsonl"
    old_session = session_root / "2026" / "06" / "02" / "old.jsonl"
    new_session = session_root / "2026" / "06" / "03" / "new.jsonl"
    project = "/work/handoff-project"
    handoff_file = "/work/handoff-project/documentation/agent-handoffs/2026-06-03.md"

    write_session(
        old_session,
        [
            {
                "timestamp": "2026-06-02T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "old-session", "cwd": project},
            },
            {
                "timestamp": "2026-06-02T12:01:00Z",
                "type": "event_msg",
                "payload": {"type": "turn_aborted"},
            },
        ],
        mtime=200,
    )
    write_session(
        new_session,
        [
            {
                "timestamp": "2026-06-03T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "new-session", "cwd": project},
            },
            {
                "timestamp": "2026-06-03T12:01:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "user_message",
                    "message": (
                        "Codex thread handoff marker:\n"
                        "source_session_id: old-session\n"
                        f"handoff_file: {handoff_file}\n"
                        f"project: {project}\n"
                        "handoff_sequence: 1"
                    ),
                },
            },
            {
                "timestamp": "2026-06-03T12:02:00Z",
                "type": "event_msg",
                "payload": {"type": "task_complete"},
            },
        ],
        mtime=100,
    )
    marker_file.parent.mkdir(parents=True)
    marker_file.write_text(
        json.dumps(
            {
                "type": "handoff_completed",
                "created_at": "2026-06-03T12:00:00Z",
                "project": project,
                "source_session_id": "old-session",
                "source_session_file": str(old_session),
                "handoff_file": handoff_file,
                "handoff_sequence": 1,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_health(
        "projects",
        "--session-root",
        str(session_root),
        "--handoff-marker-file",
        str(marker_file),
        "--safe-test-mode",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"]["projects"] == 1
    assert payload["summary"]["danger"] == 0
    project_payload = payload["projects"][0]
    assert project_payload["session_id"] == "new-session"
    assert project_payload["file"] == str(new_session)
    assert project_payload["status"] == "ok"
    assert project_payload["replaces_session_ids"] == ["old-session"]
    assert project_payload["handoff_lineage"] == {
        "status": "replacement-active",
        "source_session_ids": ["old-session"],
        "total_handoffs": 1,
    }
    assert project_payload["action"]["status"] in {"continue", "finish-current-turn"}
    assert project_payload["handoff_summary"]["total_handoffs"] == 1
    assert project_payload["handoff_summary"]["retired_source_sessions"] == 1
    assert project_payload["handoff_summary"]["latest_handoff_file"] == handoff_file

    pretty = run_health(
        "projects",
        "--session-root",
        str(session_root),
        "--handoff-marker-file",
        str(marker_file),
        "--safe-test-mode",
    )

    assert pretty.returncode == 0, pretty.stderr
    assert "Action Summary" in pretty.stdout
    assert "Handoffs: 1 total" in pretty.stdout
    assert "Replacement for: old-session" in pretty.stdout


def test_projects_reports_backfilled_sidecar_replacement_thread(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    marker_file = tmp_path / "markers" / "handoff-markers.jsonl"
    old_session = session_root / "2026" / "06" / "02" / "old.jsonl"
    new_session = session_root / "2026" / "06" / "03" / "new.jsonl"
    project = "/work/backfilled-handoff-project"
    handoff_file = "/work/backfilled-handoff-project/documentation/agent-handoffs/2026-06-03.md"

    write_session(
        old_session,
        [
            {
                "timestamp": "2026-06-02T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "old-session", "cwd": project},
            },
            {
                "timestamp": "2026-06-02T12:01:00Z",
                "type": "event_msg",
                "payload": {"type": "turn_aborted"},
            },
        ],
        mtime=200,
    )
    write_session(
        new_session,
        [
            {
                "timestamp": "2026-06-03T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "new-session", "cwd": project},
            },
            {
                "timestamp": "2026-06-03T12:02:00Z",
                "type": "event_msg",
                "payload": {"type": "task_complete"},
            },
        ],
        mtime=100,
    )
    marker_file.parent.mkdir(parents=True)
    marker_file.write_text(
        json.dumps(
            {
                "type": "handoff_completed",
                "created_at": "2026-06-03T12:00:00Z",
                "project": project,
                "source_session_id": "old-session",
                "source_session_file": str(old_session),
                "replacement_session_id": "new-session",
                "replacement_session_file": str(new_session),
                "handoff_file": handoff_file,
                "handoff_sequence": 1,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_health(
        "projects",
        "--session-root",
        str(session_root),
        "--handoff-marker-file",
        str(marker_file),
        "--safe-test-mode",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    project_payload = payload["projects"][0]
    assert project_payload["session_id"] == "new-session"
    assert project_payload["file"] == str(new_session)
    assert project_payload["status"] == "ok"
    assert project_payload["replaces_session_ids"] == ["old-session"]
    assert project_payload["handoff_lineage"] == {
        "status": "replacement-active",
        "source_session_ids": ["old-session"],
        "total_handoffs": 1,
    }
    assert project_payload["action"]["status"] in {"continue", "finish-current-turn"}


def test_check_retired_source_session_reports_handoff_metadata(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    marker_file = tmp_path / "markers" / "handoff-markers.jsonl"
    source_session = session_root / "2026" / "06" / "02" / "source.jsonl"
    project = "/work/retired-project"
    handoff_file = "/work/retired-project/documentation/agent-handoffs/2026-06-03.md"

    write_session(
        source_session,
        [
            {
                "timestamp": "2026-06-02T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "source-session", "cwd": project},
            },
            {
                "timestamp": "2026-06-02T12:01:00Z",
                "type": "event_msg",
                "payload": {"type": "turn_aborted"},
            },
        ],
    )
    marker_file.parent.mkdir(parents=True)
    marker_file.write_text(
        json.dumps(
            {
                "type": "handoff_completed",
                "created_at": "2026-06-03T12:00:00Z",
                "project": project,
                "source_session_id": "source-session",
                "source_session_file": str(source_session),
                "handoff_file": handoff_file,
                "handoff_sequence": 3,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_health(
        "check",
        str(source_session),
        "--handoff-marker-file",
        str(marker_file),
        "--json",
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "retired"
    assert payload["continuation_status"] == "retired"
    assert payload["recommendation"] == "use-replacement-thread"
    assert payload["underlying_status"] == "danger"
    assert payload["handoff_readiness"]["status"] == "completed"
    assert payload["handoff_lineage"] == {
        "status": "source-retired",
        "source_session_ids": ["source-session"],
        "total_handoffs": 1,
    }
    assert payload["action"] == {
        "status": "use-replacement",
        "reason": "this source session was retired by a completed handoff",
    }
    assert payload["retired_by_handoff"]["handoff_file"] == handoff_file
    assert payload["retired_by_handoff"]["handoff_sequence"] == 3
    assert payload["handoff_summary"]["total_handoffs"] == 1

    pretty = run_health(
        "check",
        str(source_session),
        "--handoff-marker-file",
        str(marker_file),
    )

    assert pretty.returncode == 0
    assert "Overall: RETIRED" in pretty.stdout
    assert "Underlying health: DANGER" in pretty.stdout
    assert "Session role: Retired by handoff" in pretty.stdout
    assert "Domain risks:" not in pretty.stdout
    assert "Why: session was retired by completed handoff" in pretty.stdout


def test_projects_reports_incomplete_replacement_prompt_marker_evidence(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    old_session = session_root / "2026" / "06" / "02" / "old.jsonl"
    new_session = session_root / "2026" / "06" / "03" / "new.jsonl"
    project = "/work/handoff-project-partial"
    handoff_file = "/work/handoff-project-partial/documentation/agent-handoffs/2026-06-03.md"

    write_session(
        old_session,
        [
            {
                "timestamp": "2026-06-02T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "old-session", "cwd": project},
            },
        ],
    )
    write_session(
        new_session,
        [
            {
                "timestamp": "2026-06-03T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "new-session", "cwd": project},
            },
            {
                "timestamp": "2026-06-03T12:01:00Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": (
                    "Codex thread handoff marker:\n"
                    "source_session_id: old-session\n"
                    f"handoff_file: {handoff_file}\n"
                    f"project: {project}\n"
                    "handoff_sequence: 1"
                )},
            },
            {
                "timestamp": "2026-06-03T12:02:00Z",
                "type": "event_msg",
                "payload": {"type": "task_complete"},
            },
        ],
    )

    result = run_health(
        "projects",
        "--session-root",
        str(session_root),
        "--safe-test-mode",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    project_payload = payload["projects"][0]
    assert project_payload["session_id"] == "new-session"
    assert project_payload["file"] == str(new_session)
    assert project_payload["status"] == "ok"
    assert project_payload["replaces_session_ids"] == ["old-session"]
    assert project_payload["handoff_lineage"] == {
        "status": "incomplete",
        "source_session_ids": ["old-session"],
        "total_handoffs": 0,
    }
    assert project_payload["action"]["status"] in {"continue", "finish-current-turn"}


def test_projects_with_only_retired_sessions_exit_ok(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    marker_file = tmp_path / "markers" / "handoff-markers.jsonl"
    source_session = session_root / "2026" / "06" / "02" / "source.jsonl"
    project = "/work/retired-only-project"

    write_session(
        source_session,
        [
            {
                "timestamp": "2026-06-02T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "source-session", "cwd": project},
            },
            {
                "timestamp": "2026-06-02T12:01:00Z",
                "type": "event_msg",
                "payload": {"type": "turn_aborted"},
            },
        ],
    )
    marker_file.parent.mkdir(parents=True)
    marker_file.write_text(
        json.dumps(
            {
                "type": "handoff_completed",
                "created_at": "2026-06-03T12:00:00Z",
                "project": project,
                "source_session_id": "source-session",
                "source_session_file": str(source_session),
                "handoff_file": "/work/retired-only-project/handoff.md",
                "handoff_sequence": 1,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_health(
        "projects",
        "--session-root",
        str(session_root),
        "--handoff-marker-file",
        str(marker_file),
        "--safe-test-mode",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"]["retired"] == 1
    assert payload["summary"]["warn"] == 0
    assert payload["summary"]["danger"] == 0
    assert payload["projects"][0]["status"] == "retired"

    pretty = run_health(
        "projects",
        "--session-root",
        str(session_root),
        "--handoff-marker-file",
        str(marker_file),
        "--safe-test-mode",
    )

    assert pretty.returncode == 0, pretty.stderr
    assert "Overall: RETIRED (0 ok, 0 warn, 0 danger, 1 retired)" in pretty.stdout
    assert "RETIRED" in pretty.stdout
    assert "/work/retired-only-project" in pretty.stdout
    assert "Action Summary" in pretty.stdout
    assert "Underlying health: DANGER" in pretty.stdout
    assert "  Domain risks:" not in pretty.stdout


def test_safe_test_mode_refuses_live_session_root() -> None:
    result = run_health(
        "projects",
        "--session-root",
        str(Path.home() / ".codex" / "sessions"),
        "--safe-test-mode",
    )

    assert result.returncode == 1
    assert "safe test mode refuses" in result.stderr


def test_projects_default_output_is_human_readable() -> None:
    result = run_health(
        "projects",
        "--session-root",
        str(FIXTURES),
        "--safe-test-mode",
        "--warn-items",
        "20",
        "--danger-items",
        "40",
    )

    assert result.returncode == 3
    assert "Codex Thread Health" in result.stdout
    assert "Overall: DANGER" in result.stdout
    assert "Projects: 11" in result.stdout
    assert "Next step: Create a handoff" in result.stdout
    assert "Project Summary" in result.stdout
    assert "Status" in result.stdout
    assert "Project" in result.stdout
    assert "Size" in result.stdout
    assert "Items" in result.stdout
    assert "Compactions" in result.stdout
    assert "Visuals" in result.stdout
    assert "Handoff" in result.stdout
    assert "Top reason" not in result.stdout
    assert "Action Summary" in result.stdout
    assert "Action" in result.stdout
    assert "Why" in result.stdout
    assert "DANGER  /work/project-c" in result.stdout
    assert "WARN    /work/project-visual" in result.stdout
    assert "OK      /work/project-a" in result.stdout
    assert "Recommendation:" not in result.stdout
    assert "Continuation health:" not in result.stdout
    assert "Handoff readiness:" not in result.stdout
    assert "Domain risks:" not in result.stdout
    assert "File:" not in result.stdout
    assert "/work/project-c" in result.stdout
    summary_table = result.stdout.split("Project Summary\n", 1)[1].split(
        "\n\nAction Summary",
        1,
    )[0]
    assert max(len(line) for line in summary_table.splitlines()) <= 120


def test_projects_table_prioritizes_project_name_for_long_paths(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    session = session_root / "2026" / "06" / "10" / "long-path.jsonl"
    project = "/Users/richolson/Documents/Atomic Mail Server"
    write_session(
        session,
        [
            {
                "timestamp": "2026-06-10T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "long-path", "cwd": project},
            },
            {
                "timestamp": "2026-06-10T12:00:00Z",
                "type": "turn_context",
                "payload": {"cwd": project, "model": "gpt-5.5"},
            },
            {
                "timestamp": "2026-06-10T12:00:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "ok"}],
                },
            },
        ],
    )

    result = run_health(
        "projects",
        "--session-root",
        str(session_root),
        "--safe-test-mode",
    )

    assert result.returncode == 0, result.stderr
    assert ".../Atomic Mail Server" in result.stdout
    assert "/Users/r...Mail Server" not in result.stdout


def test_projects_action_summary_expands_full_reasons() -> None:
    result = run_health(
        "projects",
        "--session-root",
        str(FIXTURES),
        "--safe-test-mode",
        "--warn-items",
        "20",
        "--danger-items",
        "40",
    )

    assert result.returncode == 3
    action_summary = result.stdout.split("\n\nAction Summary\n", 1)[1]
    assert "WARN: /work/project-visual" in action_summary
    assert "  Action: Monitor" in action_summary
    assert "  Why:" in action_summary
    assert "- visual references exist inside compacted replacement history" in action_summary
    assert (
        "- compaction failure or context-window error event was recorded"
        in action_summary
    )
    assert "visual references ex..." not in action_summary
    assert "compaction failure o..." not in action_summary


def test_projects_verbose_keeps_diagnostic_blocks() -> None:
    result = run_health(
        "projects",
        "--session-root",
        str(FIXTURES),
        "--safe-test-mode",
        "--mode",
        "verbose",
        "--warn-items",
        "20",
        "--danger-items",
        "40",
    )

    assert result.returncode == 3
    assert "Attention Required" in result.stdout
    assert "Project Summary" not in result.stdout
    assert "Action Summary" not in result.stdout
    assert "Recommendation:" in result.stdout
    assert "Continuation health:" in result.stdout
    assert "Handoff readiness:" in result.stdout
    assert "Domain risks:" in result.stdout
    assert "File:" in result.stdout


def test_health_output_modes_parse_for_all_commands() -> None:
    for mode in ("compact", "standard", "verbose"):
        check = run_health(
            "check",
            str(FIXTURES / "healthy.jsonl"),
            "--safe-test-mode",
            "--mode",
            mode,
        )
        assert check.returncode == 0, check.stderr
        assert "Codex Thread Health" in check.stdout

        projects = run_health(
            "projects",
            "--session-root",
            str(FIXTURES),
            "--safe-test-mode",
            "--mode",
            mode,
            "--warn-items",
            "20",
            "--danger-items",
            "40",
        )
        assert projects.returncode == 3, projects.stderr
        assert "Codex Thread Health" in projects.stdout

        tokens = run_health(
            "tokens",
            "--session-root",
            str(FIXTURES),
            "--safe-test-mode",
            "--mode",
            mode,
        )
        assert tokens.returncode == 0, tokens.stderr
        assert "Codex Project Token Usage" in tokens.stdout


def test_size_format_applies_to_health_output() -> None:
    human = run_health(
        "check",
        str(FIXTURES / "healthy.jsonl"),
        "--safe-test-mode",
        "--size-format",
        "human",
    )
    both = run_health(
        "check",
        str(FIXTURES / "healthy.jsonl"),
        "--safe-test-mode",
        "--size-format",
        "both",
    )

    assert human.returncode == 0, human.stderr
    assert "bytes" not in human.stdout
    assert "MiB" in human.stdout or "KiB" in human.stdout
    assert both.returncode == 0, both.stderr
    assert "bytes)" in both.stdout
    assert "MiB" in both.stdout or "KiB" in both.stdout


def test_format_json_alias_keeps_stdout_machine_readable() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "healthy.jsonl"),
        "--safe-test-mode",
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    payload = assert_json_stdout(result)
    assert payload["status"] == "ok"


def test_options_only_defaults_to_projects_scan() -> None:
    result = run_health(
        "--session-root",
        str(FIXTURES),
        "--safe-test-mode",
        "--warn-items",
        "20",
        "--danger-items",
        "40",
    )

    assert result.returncode == 3
    assert "Codex Thread Health" in result.stdout
    assert "Session folder:" in result.stdout


def test_json_stdout_stays_clean_when_progress_is_forced() -> None:
    commands = [
        (
            "check",
            str(FIXTURES / "healthy.jsonl"),
            "--safe-test-mode",
        ),
        (
            "projects",
            "--session-root",
            str(FIXTURES),
            "--safe-test-mode",
            "--warn-items",
            "20",
            "--danger-items",
            "40",
        ),
        (
            "tokens",
            "--session-root",
            str(FIXTURES),
            "--safe-test-mode",
        ),
    ]

    for command in commands:
        result = run_health(*command, "--json", "--progress", "always")
        assert result.returncode in {0, 2, 3}, result.stderr
        assert_json_stdout(result)
        assert result.stderr


def test_progress_uses_size_format() -> None:
    bytes_result = run_health(
        "check",
        str(FIXTURES / "healthy.jsonl"),
        "--safe-test-mode",
        "--progress",
        "always",
    )
    human_result = run_health(
        "check",
        str(FIXTURES / "healthy.jsonl"),
        "--safe-test-mode",
        "--progress",
        "always",
        "--size-format",
        "human",
    )

    assert bytes_result.returncode == 0, bytes_result.stderr
    assert " bytes)" in bytes_result.stderr
    assert "," in bytes_result.stderr
    assert human_result.returncode == 0, human_result.stderr
    assert " bytes)" not in human_result.stderr
    assert "KiB)" in human_result.stderr or "MiB)" in human_result.stderr


def test_discussion_of_compaction_failure_is_not_a_failure_signal() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "discussion-only.jsonl"),
        "--safe-test-mode",
        "--json",
        "--warn-items",
        "20",
        "--danger-items",
        "40",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["recommendation"] == "continue"
    assert payload["metrics"]["compaction_failures"] == []
    assert payload["risk_domains"]["compaction"]["status"] == "ok"


def test_event_message_discussion_of_compaction_failure_is_not_signal(tmp_path: Path) -> None:
    session = tmp_path / "event-discussion.jsonl"
    records = [
        {
            "timestamp": "2026-05-24T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": "event-discussion", "cwd": "/work/event-discussion"},
        },
        {
            "timestamp": "2026-05-24T12:00:00Z",
            "type": "turn_context",
            "payload": {"cwd": "/work/event-discussion", "model": "gpt-5.5"},
        },
        {
            "timestamp": "2026-05-24T12:00:00Z",
            "type": "event_msg",
            "payload": {
                "type": "agent_message",
                "message": "I read about remote compaction failed messages in docs.",
            },
        },
        {
            "timestamp": "2026-05-24T12:00:00Z",
            "type": "event_msg",
            "payload": {"type": "turn_complete", "message": "turn complete"},
        },
    ]
    session.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )

    result = run_health("check", str(session), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["metrics"]["compaction_failures"] == []
    assert payload["risk_domains"]["compaction"]["status"] == "ok"


def test_cumulative_token_total_does_not_drive_active_context_danger() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "token-cumulative-high.jsonl"),
        "--safe-test-mode",
        "--json",
        "--warn-items",
        "20",
        "--danger-items",
        "40",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["metrics"]["latest_token_total"] == 2_000_000
    assert payload["metrics"]["latest_active_token_total"] == 40_000
    assert payload["metrics"]["token_count_events"] == 1
    assert payload["metrics"]["first_token_timestamp"] == "2026-05-24T12:00:00Z"
    assert payload["metrics"]["latest_token_timestamp"] == "2026-05-24T12:00:00Z"
    assert payload["metrics"]["latest_token_usage"]["total_tokens"] == 2_000_000
    assert payload["metrics"]["latest_active_token_usage"]["total_tokens"] == 40_000
    assert payload["metrics"]["latest_token_ratio"] == 0.1548
    assert payload["metrics"]["latest_cumulative_token_ratio"] == 7.7399
    assert payload["risk_domains"]["limits"]["status"] == "ok"


def test_real_persisted_event_failure_recommends_handoff_now() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "event-failure.jsonl"),
        "--safe-test-mode",
        "--json",
    )

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "danger"
    assert payload["recommendation"] == "handoff-now"
    assert payload["risk_domains"]["compaction"]["status"] == "danger"
    assert payload["risk_domains"]["continuity"]["status"] == "danger"


def test_multiple_token_events_use_latest_cumulative_total() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "token-multiple-events.jsonl"),
        "--safe-test-mode",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["metrics"]["token_count_events"] == 2
    assert payload["metrics"]["latest_token_total"] == 3_000
    assert payload["metrics"]["latest_active_token_total"] == 2_000


def test_json_report_includes_risk_domains() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "compaction-success.jsonl"),
        "--safe-test-mode",
        "--json",
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert set(payload["risk_domains"]) == {
        "load",
        "visuals",
        "compaction",
        "limits",
        "continuity",
    }
    assert payload["overall_assessment"] == "continue"


def test_check_visual_embedded_fixture_reports_visual_metrics() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "visual-embedded-image.jsonl"),
        "--safe-test-mode",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["metrics"]["visual_artifacts"] == 1
    assert payload["metrics"]["visual_embedded_artifacts"] == 1
    assert payload["metrics"]["visual_embedded_bytes"] > 0
    assert payload["metrics"]["visual_video_artifacts"] == 0
    assert payload["risk_domains"]["visuals"]["status"] == "ok"
    assert payload["continuation_status"] == "ok"
    assert payload["handoff_readiness"]["status"] == "not-needed"
    assert payload["handoff_readiness"]["visual_archive"] == "recommended"
    assert any("visual" in reason for reason in payload["handoff_readiness"]["reasons"])


def test_check_visual_compacted_fixture_warns_about_visuals_inside_compaction() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "visual-compacted-image.jsonl"),
        "--safe-test-mode",
        "--json",
    )

    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["metrics"]["visual_artifacts_in_compacted_records"] == 1
    assert payload["status"] == "warn"
    assert payload["recommendation"] == "monitor"
    assert payload["risk_domains"]["visuals"]["status"] == "warn"
    assert any("visual" in reason for reason in payload["reasons"])
    assert payload["continuation_risk"]["status"] == "ok"
    assert payload["notices"] == [COMPACTED_VISUAL_REFERENCE_DIAGNOSTIC]
    assert payload["action"] == {
        "status": "continue",
        "reason": "no continuation risk requires a handoff",
    }


def test_check_response_items_warning_scale_requests_prepared_handoff(
    tmp_path: Path,
) -> None:
    session = tmp_path / "warningscale-response-items.jsonl"
    records = [
        {
            "timestamp": "2026-05-24T12:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "response-items-warning-scale",
                "cwd": "/work/warningscale",
            },
        }
    ]
    for index in range(9):
        records.append(
            {
                "timestamp": "2026-05-24T12:00:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": str(index)}],
                },
            }
        )
    write_session(session, records)

    result = run_health(
        "check",
        str(session),
        "--safe-test-mode",
        "--warn-items",
        "8",
        "--danger-items",
        "12",
        "--json",
    )

    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "warn"
    assert payload["recommendation"] == "monitor"
    assert payload["reasons"] == [
        "response_items is 9, at or above warning threshold"
    ]
    assert payload["continuation_risk"] == {
        "status": "watch",
        "reasons": ["response_items is 9, at or above warning threshold"],
    }
    assert payload["scale"] == {
        "status": "watch",
        "size": "ok",
        "items": "watch",
        "compactions": "ok",
        "visuals": "ok",
    }
    assert payload["action"] == {
        "status": "prepare-handoff",
        "reason": "continuation risk should be addressed with a deliberate handoff",
    }


def test_check_visual_embedded_warning_scale_marks_watch() -> None:
    from codex_thread_tools import thread_health
    from codex_thread_tools.thread_health import HealthThresholds, analyze_session_file

    def visual_metrics_stub(record: dict[str, object]) -> dict[str, int | float]:
        return {
            "visual_artifacts": 1,
            "visual_embedded_artifacts": 1,
            "visual_local_references": 0,
            "visual_video_artifacts": 0,
            "visual_embedded_bytes": 51 * 1024 * 1024,
            "largest_visual_artifact_bytes": 49 * 1024 * 1024,
            "visual_artifact_errors": 0,
            "visual_artifact_skipped": 0,
        }

    session = Path("/tmp") / "visual-embedded-warning-scale.jsonl"
    write_session(
        session,
        [
            {
                "timestamp": "2026-06-02T12:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "visual-embedded-warning-scale",
                    "cwd": "/work/visual-warning-scale",
                    },
                },
            {
                "timestamp": "2026-06-02T12:01:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "visual threshold fixture"}],
                },
            },
        ],
    )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        thread_health,
        "scan_record_visual_metrics",
        visual_metrics_stub,
    )
    try:
        payload = analyze_session_file(session, HealthThresholds())
    finally:
        monkeypatch.undo()

    assert payload["scale"] == {
        "status": "watch",
        "size": "ok",
        "items": "ok",
        "compactions": "ok",
        "visuals": "watch",
    }


def test_replay_integrity_failure_requires_handoff_now(tmp_path: Path) -> None:
    session = tmp_path / "replay-failure.jsonl"
    write_session(
        session,
        [
            {
                "timestamp": "2026-05-24T12:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "replay-failure",
                    "cwd": "/work/replay-failure",
                },
            },
            {
                "timestamp": "2026-05-24T12:01:00Z",
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
            },
        ],
    )

    result = run_health(
        "check",
        str(session),
        "--safe-test-mode",
        "--json",
    )

    assert result.returncode == 3, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "danger"
    assert payload["recommendation"] == "handoff-now"
    assert "invalid model-visible image URL can break thread replay" in payload["reasons"]
    assert payload["continuation_risk"]["status"] == "danger"
    assert payload["action"]["status"] == "handoff-now"


def test_visual_health_estimates_large_embedded_payload_without_hashing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from codex_thread_tools import visual_artifacts
    from codex_thread_tools.thread_health import HealthThresholds, analyze_session_file

    huge = base64.b64encode(b"x" * 1024).decode("ascii")
    session = tmp_path / "large-visual.jsonl"
    records = [
        {"timestamp": "2026-05-24T12:00:00Z", "type": "session_meta", "payload": {"cwd": "/tmp"}},
        {
            "timestamp": "2026-05-24T12:00:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_image", "image_url": f"data:image/png;base64,{huge}"}],
            },
        },
    ]
    session.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")

    def fail_hash(_: bytes) -> str:
        raise AssertionError("health analysis should not hash embedded visual bytes")

    monkeypatch.setattr(visual_artifacts.hashlib, "sha256", fail_hash)

    payload = analyze_session_file(session, HealthThresholds())

    assert payload["metrics"]["visual_embedded_artifacts"] == 1
    assert payload["metrics"]["visual_embedded_bytes"] == 1024


def test_pretty_output_includes_domain_breakdown() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "event-failure.jsonl"),
        "--safe-test-mode",
    )

    assert result.returncode == 3
    assert "Domain Risks" in result.stdout
    assert "Key Facts" in result.stdout
    assert result.stdout.index("Domain Risks") < result.stdout.index("Key Facts")
    assert "\n\nKey Facts\n" in result.stdout
    assert "\n\nWhy:" in result.stdout
    assert "Status" in result.stdout
    assert "DANGER" in result.stdout
    assert "Continuation health: DANGER" in result.stdout
    assert "Handoff readiness: Needed" in result.stdout
    assert "Visuals" in result.stdout
    assert "Compaction" in result.stdout
    assert "Continuity" in result.stdout
    assert "Why" in result.stdout
    assert "File:" in result.stdout


def test_task_started_and_task_complete_aliases_are_counted() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "event-aliases.jsonl"),
        "--safe-test-mode",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["metrics"]["turn_started_events"] == 1
    assert payload["metrics"]["turn_complete_events"] == 1
    assert payload["risk_domains"]["continuity"]["status"] == "ok"


def test_historical_turn_abort_recovered_by_completion_warns(tmp_path: Path) -> None:
    session = tmp_path / "recovered-abort.jsonl"
    records = [
        {
            "timestamp": "2026-06-02T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": "recovered-abort", "cwd": "/work/recovered"},
        },
        {
            "timestamp": "2026-06-02T12:01:00Z",
            "type": "event_msg",
            "payload": {"type": "task_started"},
        },
        {
            "timestamp": "2026-06-02T12:02:00Z",
            "type": "event_msg",
            "payload": {"type": "turn_aborted"},
        },
        {
            "timestamp": "2026-06-02T12:03:00Z",
            "type": "event_msg",
            "payload": {"type": "task_started"},
        },
        {
            "timestamp": "2026-06-02T12:04:00Z",
            "type": "event_msg",
            "payload": {"type": "task_complete"},
        },
    ]
    session.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )

    result = run_health("check", str(session), "--json")

    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "warn"
    assert payload["continuation_status"] == "warn"
    assert payload["recommendation"] == "monitor"
    assert payload["risk_domains"]["continuity"]["status"] == "warn"
    assert payload["metrics"]["turn_aborted_events"] == 1
    assert payload["metrics"]["recovered_turn_error_events"] == 1
    assert payload["metrics"]["unresolved_turn_error_events"] == 0
    assert payload["notices"] == [
        "historical turn abort or error event was recovered by later completion"
    ]
    assert payload["continuation_risk"] == {"status": "ok", "reasons": []}
    assert payload["action"] == {
        "status": "continue",
        "reason": "no continuation risk requires a handoff",
    }
    assert payload["scale"]["status"] == "ok"


def test_latest_turn_abort_remains_danger(tmp_path: Path) -> None:
    session = tmp_path / "unresolved-abort.jsonl"
    records = [
        {
            "timestamp": "2026-06-02T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": "unresolved-abort", "cwd": "/work/unresolved"},
        },
        {
            "timestamp": "2026-06-02T12:01:00Z",
            "type": "event_msg",
            "payload": {"type": "task_started"},
        },
        {
            "timestamp": "2026-06-02T12:02:00Z",
            "type": "event_msg",
            "payload": {"type": "turn_aborted"},
        },
    ]
    session.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )

    result = run_health("check", str(session), "--json")

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "danger"
    assert payload["risk_domains"]["continuity"]["status"] == "danger"
    assert payload["metrics"]["unresolved_turn_error_events"] == 1


def test_incomplete_turn_blocks_clean_handoff_recommendation(tmp_path: Path) -> None:
    session = tmp_path / "incomplete-turn.jsonl"
    write_session(
        session,
        [
            {
                "timestamp": "2026-06-02T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "incomplete-turn", "cwd": "/work/incomplete"},
            },
            {
                "timestamp": "2026-06-02T12:01:00Z",
                "type": "event_msg",
                "payload": {"type": "turn_started"},
            }
        ],
    )

    result = run_health("check", str(session), "--json")

    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "warn"
    assert payload["recommendation"] == "monitor"
    assert payload["handoff_readiness"]["status"] == "recommended"
    assert payload["task_state"] == {
        "status": "active",
        "reason": "latest recorded turn has no terminal event",
    }
    assert payload["continuation_risk"] == {
        "status": "ok",
        "reasons": [],
    }
    assert payload["notices"] == [ACTIVE_TURN_DIAGNOSTIC]
    assert payload["action"] == {
        "status": "finish-current-turn",
        "reason": "task is active; no continuation risk requires a handoff",
    }
    assert payload["metrics"]["incomplete_turn_events"] == 1
    assert payload["metrics"]["latest_turn_event"] == "turn_started"
    assert payload["risk_domains"]["continuity"]["status"] == "warn"
    assert any("active turn" in reason for reason in payload["reasons"])


def test_generic_runtime_error_is_not_a_compaction_failure() -> None:
    result = run_health(
        "check",
        str(FIXTURES / "runtime-error.jsonl"),
        "--safe-test-mode",
        "--json",
    )

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["metrics"]["compaction_failures"] == []
    assert payload["risk_domains"]["compaction"]["status"] == "ok"
    assert payload["risk_domains"]["continuity"]["status"] == "danger"


def test_tokens_json_reports_lifetime_usage_by_project() -> None:
    result = run_health(
        "tokens",
        "--session-root",
        str(FIXTURES),
        "--safe-test-mode",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"]["projects"] == 11
    assert payload["summary"]["sessions"] == 19
    assert payload["summary"]["projects_with_token_usage"] == 3
    assert payload["summary"]["sessions_with_token_usage"] == 4
    assert payload["summary"]["reported_lifetime_tokens"] == 2_353_000

    projects = payload["projects"]
    assert projects[0]["project"] == "/work/project-f"
    assert projects[0]["lifetime_tokens"] == 2_100_000
    assert projects[0]["sessions"] == 2
    assert projects[0]["sessions_with_token_usage"] == 2
    assert projects[0]["latest_active_tokens"] == 40_000
    assert projects[0]["latest_active_context_percent"] == 15.48
    assert projects[0]["latest_token_timestamp"] == "2026-05-24T12:00:00Z"
    assert {source["lifetime_tokens"] for source in projects[0]["sources"]} == {
        2_000_000,
        100_000,
    }

    assert projects[1]["project"] == "/work/project-e"
    assert projects[1]["lifetime_tokens"] == 250_000
    assert projects[2]["project"] == "/work/project-j"
    assert projects[2]["lifetime_tokens"] == 3_000
    assert projects[-1]["lifetime_tokens"] is None


def test_tokens_pretty_output_is_human_readable() -> None:
    result = run_health(
        "tokens",
        "--session-root",
        str(FIXTURES),
        "--safe-test-mode",
    )

    assert result.returncode == 0, result.stderr
    assert "Codex Project Token Usage" in result.stdout
    assert "Reported lifetime tokens: 2,353,000" in result.stdout
    assert "Project Token Summary" in result.stdout
    assert "Project" in result.stdout
    assert "Lifetime" in result.stdout
    assert "Active" in result.stdout
    assert "Context" in result.stdout
    assert "Events" in result.stdout
    assert "/work/project-f" in result.stdout
    assert "2,100,000" in result.stdout
    assert "15.48%" in result.stdout
    assert "not recorded" in result.stdout


def test_tokens_verbose_output_keeps_latest_file_details() -> None:
    result = run_health(
        "tokens",
        "--session-root",
        str(FIXTURES),
        "--safe-test-mode",
        "--mode",
        "verbose",
    )

    assert result.returncode == 0, result.stderr
    assert "Latest file:" in result.stdout
    assert "Token events: 0" in result.stdout
    assert "not recorded" in result.stdout
