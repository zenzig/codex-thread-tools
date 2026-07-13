import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from codex_thread_tools.remote_health import add_remote_metadata
from codex_thread_tools.remote_health import build_ssh_argv
from codex_thread_tools.remote_health import (
    RemoteHealthError,
    ensure_compatible_versions,
    run_remote_health,
    select_remote_project,
    validate_projects_report,
)


ROOT = Path(__file__).resolve().parents[1]


def fixture_projects_report() -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "codex-thread-health.py"),
            "projects",
            "--session-root",
            str(ROOT / "tests" / "fixtures" / "sessions"),
            "--safe-test-mode",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode in {0, 2, 3}, result.stderr
    return json.loads(result.stdout)


@pytest.fixture
def projects_payload() -> dict:
    return validate_projects_report(
        {
            "session_root": "/remote/sessions",
            "summary": {
                "projects": 4,
                "ok": 1,
                "warn": 1,
                "danger": 1,
                "retired": 1,
            },
            "projects": [
                {
                    "project": "/work/project-a",
                    "status": "ok",
                    "recommendation": "continue",
                    "metrics": {},
                    "reasons": [],
                    "handoff_readiness": {},
                },
                {
                    "project": "/work/project-b",
                    "status": "warn",
                    "recommendation": "review",
                    "metrics": {},
                    "reasons": [],
                    "handoff_readiness": {},
                },
                {
                    "project": "/work/project-c",
                    "status": "danger",
                    "recommendation": "handoff-now",
                    "metrics": {},
                    "reasons": [],
                    "handoff_readiness": {},
                },
                {
                    "project": "/work/project-d",
                    "status": "retired",
                    "recommendation": "archive",
                    "metrics": {},
                    "reasons": [],
                    "handoff_readiness": {},
                },
            ],
        }
    )


def test_select_remote_project_recomputes_summary(projects_payload: dict) -> None:
    selected = select_remote_project(projects_payload, "/work/project-b")

    assert [item["project"] for item in selected["projects"]] == [
        "/work/project-b"
    ]
    assert selected["summary"] == {
        "projects": 1,
        "ok": 0,
        "warn": 1,
        "danger": 0,
        "retired": 0,
    }


def test_select_remote_project_rejects_absent_path(projects_payload: dict) -> None:
    with pytest.raises(
        RemoteHealthError,
        match=r"remote project was not found: /work/missing",
    ):
        select_remote_project(projects_payload, "/work/missing")


def test_add_remote_metadata_does_not_mutate_input(projects_payload: dict) -> None:
    result = add_remote_metadata(projects_payload, "node1.atomicfalls.com")

    assert result["source"] == "remote"
    assert result["host"] == "node1.atomicfalls.com"
    assert "source" not in projects_payload


def test_malicious_project_path_is_exact_and_not_forwarded_to_ssh(
    projects_payload: dict,
) -> None:
    malicious = "/home/rich/atomic-development; touch /tmp/project-injection"
    projects_payload["projects"].append(
        {
            "project": malicious,
            "status": "ok",
            "recommendation": "continue",
            "metrics": {},
            "reasons": [],
            "handoff_readiness": {},
        }
    )
    calls, runner = make_runner(projects_payload)

    report, _returncode, _warning = run_remote_health(
        "node1.atomicfalls.com",
        ["health", "projects"],
        local_version="1.0.0",
        runner=runner,
    )
    selected = select_remote_project(report, malicious)

    assert selected["projects"][0]["project"] == malicious
    assert all(malicious not in command[-1] for command, _kwargs in calls)


def test_build_ssh_argv_keeps_host_and_remote_arguments_inert() -> None:
    argv = build_ssh_argv(
        "user@example.test",
        [
            "codex-thread-tools",
            "health",
            "projects",
            "--warn-items",
            "8000; touch /tmp/should-not-exist",
        ],
        connect_timeout=7,
        ssh_executable="/test/bin/ssh",
    )

    assert argv[:6] == [
        "/test/bin/ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=7",
        "--",
    ]
    assert argv[6] == "user@example.test"
    assert argv[7] == (
        "codex-thread-tools health projects --warn-items "
        "'8000; touch /tmp/should-not-exist'"
    )


def test_run_remote_health_rejects_option_like_host_before_execution() -> None:
    def runner(_argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("runner must not be called")

    with pytest.raises(
        RemoteHealthError,
        match=re.escape("SSH host must be a non-empty destination"),
    ):
        run_remote_health(
            "-unsafe-host",
            ["health", "projects"],
            local_version="1.0.0",
            runner=runner,
        )


def test_equal_versions_need_no_warning() -> None:
    assert ensure_compatible_versions("1.1.0", "1.1.0") is None


def test_minor_mismatch_returns_warning() -> None:
    assert ensure_compatible_versions("1.1.0", "1.2.3") == (
        "remote version differs: local 1.1.0, remote 1.2.3"
    )


def test_major_version_mismatch_is_rejected() -> None:
    with pytest.raises(RemoteHealthError, match="incompatible remote version"):
        ensure_compatible_versions("1.1.0", "2.0.0")


@pytest.mark.parametrize("value", ["", "latest", "1", "1.2", "v1.2.3"])
def test_invalid_remote_version_is_rejected(value: str) -> None:
    with pytest.raises(RemoteHealthError, match="invalid version"):
        ensure_compatible_versions("1.1.0", value)


@pytest.mark.parametrize(
    "case",
    ["non_object", "missing_root", "summary", "projects_not_list", "project"],
)
def test_validate_projects_report_rejects_invalid_shape(case: str) -> None:
    payload: object
    if case == "non_object":
        payload = None
    elif case == "missing_root":
        payload = {}
    else:
        payload = fixture_projects_report()
        if case == "summary":
            payload["summary"] = {}
        elif case == "projects_not_list":
            payload["projects"] = {}
        else:
            payload["projects"] = [{}]

    with pytest.raises(RemoteHealthError, match="invalid remote health report"):
        validate_projects_report(payload)


def test_validate_projects_report_accepts_fixture_payload() -> None:
    payload = fixture_projects_report()

    validated = validate_projects_report(payload)

    assert validated == payload


def make_runner(
    report: dict,
    *,
    health_returncode: int = 0,
    health_stdout: str | None = None,
    health_stderr: str = "",
    version_stdout: str = "1.0.0\n",
    version_returncode: int = 0,
    version_stderr: str = "",
) -> tuple[list[tuple[list[str], dict]], object]:
    calls: list[tuple[list[str], dict]] = []

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = shlex.split(argv[-1])
        calls.append((command, kwargs))
        if command == ["codex-thread-tools", "--version"]:
            return subprocess.CompletedProcess(
                argv,
                version_returncode,
                stdout=version_stdout,
                stderr=version_stderr,
            )
        return subprocess.CompletedProcess(
            argv,
            health_returncode,
            stdout=json.dumps(report) if health_stdout is None else health_stdout,
            stderr=health_stderr,
        )

    return calls, runner


@pytest.mark.parametrize("returncode", [0, 2, 3])
def test_run_remote_health_probes_version_and_returns_report(
    returncode: int,
) -> None:
    report = fixture_projects_report()
    calls, runner = make_runner(report, health_returncode=returncode)
    remote_args = ["health", "projects"]

    result = run_remote_health(
        "node1.atomicfalls.com",
        remote_args,
        local_version="1.0.0",
        connect_timeout=7,
        ssh_executable="/test/bin/ssh",
        runner=runner,
    )

    assert result == (report, returncode, None)
    assert remote_args == ["health", "projects"]
    assert [command for command, _kwargs in calls] == [
        ["codex-thread-tools", "--version"],
        [
            "codex-thread-tools",
            "health",
            "projects",
            "--json",
            "--progress",
            "never",
        ],
    ]
    for _command, kwargs in calls:
        assert kwargs == {
            "text": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "check": False,
            "shell": False,
            "timeout": 12,
        }


def test_run_remote_health_returns_version_drift_warning() -> None:
    report = fixture_projects_report()
    calls, runner = make_runner(report, version_stdout="1.1.0\n")

    result = run_remote_health(
        "node1.atomicfalls.com",
        ["health", "projects"],
        local_version="1.0.0",
        runner=runner,
    )

    assert result == (
        report,
        0,
        "remote version differs: local 1.0.0, remote 1.1.0",
    )


@pytest.mark.parametrize(
    ("version_returncode", "version_stderr", "expected"),
    [
        (
            255,
            "Permission denied (publickey)\n",
            "SSH command failed for node1.atomicfalls.com: Permission denied (publickey)",
        ),
        (
            127,
            "codex-thread-tools: command not found\n",
            "remote codex-thread-tools is not installed or not available to "
            "non-interactive SSH on node1.atomicfalls.com",
        ),
    ],
)
def test_run_remote_health_maps_version_probe_failures(
    version_returncode: int,
    version_stderr: str,
    expected: str,
) -> None:
    calls, runner = make_runner(
        fixture_projects_report(),
        version_returncode=version_returncode,
        version_stderr=version_stderr,
    )

    with pytest.raises(RemoteHealthError, match=re.escape(expected)):
        run_remote_health(
            "node1.atomicfalls.com",
            ["health", "projects"],
            local_version="1.0.0",
            runner=runner,
        )

    assert len(calls) == 1


def test_run_remote_health_maps_health_command_failure() -> None:
    calls, runner = make_runner(
        fixture_projects_report(),
        health_returncode=1,
        health_stderr="remote health exploded\n",
    )

    with pytest.raises(
        RemoteHealthError,
        match=re.escape(
            "remote health command failed on node1.atomicfalls.com: "
            "remote health exploded"
        ),
    ):
        run_remote_health(
            "node1.atomicfalls.com",
            ["health", "projects"],
            local_version="1.0.0",
            runner=runner,
        )

    assert len(calls) == 2


def test_run_remote_health_rejects_malformed_json_without_echoing_stdout() -> None:
    secret = "remote-secret-sentinel"
    calls, runner = make_runner(
        fixture_projects_report(),
        health_stdout=f"{{not-json:{secret}}}",
    )

    with pytest.raises(
        RemoteHealthError,
        match=re.escape(
            "remote health command returned malformed JSON from "
            "node1.atomicfalls.com"
        ),
    ) as error:
        run_remote_health(
            "node1.atomicfalls.com",
            ["health", "projects"],
            local_version="1.0.0",
            runner=runner,
        )

    assert secret not in str(error.value)


def test_run_remote_health_maps_missing_ssh_executable() -> None:
    def runner(_argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    with pytest.raises(
        RemoteHealthError,
        match=re.escape("SSH executable was not found: /test/bin/ssh"),
    ):
        run_remote_health(
            "node1.atomicfalls.com",
            ["health", "projects"],
            local_version="1.0.0",
            ssh_executable="/test/bin/ssh",
            runner=runner,
        )


def test_run_remote_health_maps_ssh_timeout() -> None:
    def runner(_argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("ssh", 15)

    with pytest.raises(
        RemoteHealthError,
        match=re.escape("SSH connection to node1.atomicfalls.com timed out"),
    ):
        run_remote_health(
            "node1.atomicfalls.com",
            ["health", "projects"],
            local_version="1.0.0",
            runner=runner,
        )


def test_run_remote_health_propagates_keyboard_interrupt() -> None:
    def runner(_argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_remote_health(
            "node1.atomicfalls.com",
            ["health", "projects"],
            local_version="1.0.0",
            runner=runner,
        )


def test_run_remote_health_caps_remote_stderr() -> None:
    calls, runner = make_runner(
        fixture_projects_report(),
        health_returncode=1,
        health_stderr="x" * 700,
    )

    with pytest.raises(RemoteHealthError) as error:
        run_remote_health(
            "node1.atomicfalls.com",
            ["health", "projects"],
            local_version="1.0.0",
            runner=runner,
        )

    message = str(error.value)
    assert message == (
        "remote health command failed on node1.atomicfalls.com: " + "x" * 500
    )
