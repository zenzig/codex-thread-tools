import json
import re
import shlex
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from codex_thread_tools.remote_health import (
    RemoteHealthError,
    add_remote_metadata,
    build_remote_safe_report,
    build_ssh_argv,
    ensure_compatible_versions,
    validate_ssh_destination,
    run_remote_health,
    select_remote_project,
    validate_projects_report,
)
from codex_thread_tools.thread_health import COMPACTION_FAILURE_DIAGNOSTIC


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


def fixture_remote_projects_report() -> dict:
    report = fixture_projects_report()
    projects = []
    for item in report["projects"]:
        project = {
            "project": item["project"],
            "file": item["file"],
            "status": item["status"],
            "continuation_status": item["continuation_status"],
            "recommendation": item["recommendation"],
            "metrics": {
                key: item["metrics"][key]
                for key in (
                    "bytes",
                    "response_items",
                    "compacted_records",
                    "visual_artifacts",
                )
            },
            "reasons": item["reasons"],
            "risk_domains": item["risk_domains"],
            "handoff_readiness": {
                "status": item["handoff_readiness"]["status"],
            },
            "handoff_summary": {
                "total_handoffs": item.get("handoff_summary", {}).get(
                    "total_handoffs", 0
                ),
                "latest_handoff_at": item.get("handoff_summary", {}).get(
                    "latest_handoff_at", ""
                ),
            },
            "replaces_session_ids": item.get("replaces_session_ids", []),
            "retired_by_handoff": bool(item.get("retired_by_handoff", False)),
        }
        if "underlying_status" in item:
            project["underlying_status"] = item["underlying_status"]
        projects.append(project)
    return {
        "remote_health_protocol": 1,
        "session_root": report["session_root"],
        "summary": report["summary"],
        "projects": projects,
    }


@pytest.fixture
def projects_payload() -> dict:
    def project_item(path: str, status: str, recommendation: str) -> dict:
        return {
            "project": path,
            "file": f"/remote/sessions/{path.rsplit('/', 1)[-1]}.jsonl",
            "status": status,
            "continuation_status": status,
            "recommendation": recommendation,
            "metrics": {
                "bytes": 0,
                "response_items": 0,
                "compacted_records": 0,
                "visual_artifacts": 0,
            },
            "reasons": [],
            "risk_domains": {
                name: {"status": "ok", "evidence": []}
                for name in (
                    "load",
                    "visuals",
                    "compaction",
                    "limits",
                    "continuity",
                )
            },
            "handoff_readiness": {"status": "not-needed"},
            "handoff_summary": {
                "total_handoffs": 0,
                "latest_handoff_at": "",
            },
            "replaces_session_ids": [],
            "retired_by_handoff": False,
        }

    return validate_projects_report(
        {
            "remote_health_protocol": 1,
            "session_root": "/remote/sessions",
            "summary": {
                "projects": 4,
                "ok": 1,
                "warn": 1,
                "danger": 1,
                "retired": 1,
            },
            "projects": [
                project_item("/work/project-a", "ok", "continue"),
                project_item("/work/project-b", "warn", "monitor"),
                project_item("/work/project-c", "danger", "handoff-now"),
                project_item(
                    "/work/project-d", "retired", "use-replacement-thread"
                ),
            ],
        }
    )


def test_select_remote_project_recomputes_summary(projects_payload: dict) -> None:
    original = deepcopy(projects_payload)

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
    assert projects_payload == original


def test_select_remote_project_with_no_filter_does_not_mutate_input(
    projects_payload: dict,
) -> None:
    original = deepcopy(projects_payload)

    selected = select_remote_project(projects_payload, None)

    assert selected == original
    assert selected is not projects_payload
    assert projects_payload == original


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
    assert "host" not in projects_payload


def test_malicious_project_path_is_exact_and_not_forwarded_to_ssh(
    projects_payload: dict,
) -> None:
    malicious = "/home/rich/atomic-development; touch /tmp/project-injection"
    projects_payload["projects"][0] = {
        **projects_payload["projects"][0],
        "project": malicious,
        "file": "/remote/sessions/malicious.jsonl",
    }
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


@pytest.mark.parametrize(
    "host",
    [
        "",
        "-oProxyCommand=bad",
        "node1\nexample.com",
        "node1\rexample.com",
        "node1\texample.com",
        "node1\x00example.com",
        "node1 example.com",
        "node1\x7fexample.com",
        "node1\u00a0example.com",
    ],
)
def test_build_ssh_argv_rejects_unsafe_host_inputs(host: str) -> None:
    with pytest.raises(
        RemoteHealthError,
        match="SSH host (must be a non-empty destination|contains whitespace or control characters)",
    ):
        build_ssh_argv(host, ["codex-thread-tools", "--version"])


@pytest.mark.parametrize(
    "host",
    [
        "node1",
        "user@example.com",
        "192.0.2.5",
        "[2001:db8::1]",
        "user@[fe80::1%en0]",
        "dev_host",
    ],
)
def test_validate_ssh_destination_accepts_safe_values(host: str) -> None:
    assert validate_ssh_destination(host) == host
    assert build_ssh_argv(
        host,
        ["codex-thread-tools", "--version"],
    )[-2] == host


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
        payload = {"remote_health_protocol": 1}
    else:
        payload = fixture_remote_projects_report()
        if case == "summary":
            payload["summary"] = {}
        elif case == "projects_not_list":
            payload["projects"] = {}
        else:
            payload["projects"] = [{}]

    with pytest.raises(RemoteHealthError, match="invalid remote health report"):
        validate_projects_report(payload)


def test_validate_projects_report_accepts_fixture_payload() -> None:
    payload = fixture_remote_projects_report()

    validated = validate_projects_report(payload)

    assert validated == payload


def test_validate_projects_report_rejects_summary_that_disagrees_with_projects() -> None:
    payload = fixture_remote_projects_report()
    payload["projects"][0]["status"] = "danger"
    payload["summary"] = {
        "projects": 0,
        "ok": 0,
        "warn": 0,
        "danger": 0,
        "retired": 0,
    }

    with pytest.raises(
        RemoteHealthError,
        match="summary does not match projects",
    ):
        validate_projects_report(payload)


def test_validate_projects_report_rejects_missing_privacy_protocol() -> None:
    payload = fixture_remote_projects_report()
    del payload["remote_health_protocol"]

    with pytest.raises(
        RemoteHealthError,
        match="privacy-safe remote health protocol",
    ):
        validate_projects_report(payload)


@pytest.mark.parametrize("location", ["metrics", "reasons", "evidence"])
def test_validate_projects_report_rejects_noncanonical_sensitive_fields(
    location: str,
) -> None:
    sentinel = f"raw-{location}-sentinel"
    payload = fixture_remote_projects_report()
    project = payload["projects"][0]
    if location == "metrics":
        project["metrics"]["compaction_failures"] = [sentinel]
    elif location == "reasons":
        project["reasons"] = [sentinel]
    else:
        project["risk_domains"]["compaction"]["evidence"] = [sentinel]

    with pytest.raises(RemoteHealthError) as error:
        validate_projects_report(payload)

    assert sentinel not in str(error.value)


def test_remote_safe_builder_replaces_diagnostics_and_drops_invalid_id_list() -> None:
    sentinel = "raw-diagnostic-and-id-sentinel"
    payload = fixture_projects_report()
    project = payload["projects"][0]
    project["reasons"] = [sentinel]
    project["risk_domains"]["compaction"]["evidence"] = [sentinel]
    project["replaces_session_ids"] = sentinel

    safe = build_remote_safe_report(payload)
    serialized = json.dumps(safe)

    assert sentinel not in serialized
    assert safe["projects"][0]["reasons"] == [
        "additional health signal omitted by remote privacy filter"
    ]
    assert safe["projects"][0]["risk_domains"]["compaction"]["evidence"] == [
        "additional health signal omitted by remote privacy filter"
    ]
    assert safe["projects"][0]["replaces_session_ids"] == []


def test_remote_safe_builder_allows_only_canonical_codex_session_ids() -> None:
    lower_uuid = "019e7100-fe04-7823-a3b6-d7ab058ccc05"
    upper_uuid = "019E7100-FE04-7823-A3B6-D7AB058CCC05"
    sentinel = "raw-marker-shaped-transcript-sentinel"
    payload = fixture_projects_report()
    payload["projects"][0]["replaces_session_ids"] = [
        lower_uuid,
        upper_uuid,
        sentinel,
    ]

    safe = build_remote_safe_report(payload)

    assert safe["projects"][0]["replaces_session_ids"] == [lower_uuid, upper_uuid]
    assert sentinel not in json.dumps(safe)


@pytest.mark.parametrize(
    "session_id",
    [
        "019e7100-fe04-7823-a3b6-d7ab058ccc05",
        "019E7100-FE04-7823-A3B6-D7AB058CCC05",
    ],
)
def test_validate_projects_report_accepts_canonical_codex_session_ids(
    session_id: str,
) -> None:
    payload = fixture_remote_projects_report()
    payload["projects"][0]["replaces_session_ids"] = [session_id]

    assert validate_projects_report(payload) == payload


def test_validate_projects_report_rejects_non_uuid_replacement_id() -> None:
    sentinel = "raw-marker-shaped-transcript-sentinel"
    payload = fixture_remote_projects_report()
    payload["projects"][0]["replaces_session_ids"] = [sentinel]

    with pytest.raises(RemoteHealthError) as error:
        validate_projects_report(payload)

    assert sentinel not in str(error.value)


def test_remote_safe_builder_drops_noncanonical_handoff_timestamp() -> None:
    sentinel = "RAW_HANDOFF_TIMESTAMP_SENTINEL_8f31"
    payload = fixture_projects_report()
    payload["projects"][0]["handoff_summary"] = {
        "total_handoffs": 1,
        "latest_handoff_at": f"2026-06-03T12:00:00Z {sentinel}",
    }

    safe = build_remote_safe_report(payload)
    serialized = json.dumps(safe)

    assert sentinel not in serialized
    assert safe["projects"][0]["handoff_summary"]["latest_handoff_at"] == ""


def test_validate_projects_report_rejects_noncanonical_handoff_timestamp() -> None:
    sentinel = "RAW_HANDOFF_TIMESTAMP_SENTINEL_d2c7"
    payload = fixture_remote_projects_report()
    payload["projects"][0]["handoff_summary"] = {
        "total_handoffs": 1,
        "latest_handoff_at": f"2026-06-03T12:00:00.123456Z{sentinel}",
    }

    with pytest.raises(RemoteHealthError) as error:
        validate_projects_report(payload)

    assert sentinel not in str(error.value)


def test_remote_safe_builder_preserves_canonical_compaction_diagnostics() -> None:
    payload = fixture_remote_projects_report()
    project = payload["projects"][0]
    project["reasons"] = [
        "untrusted diagnostic",
        COMPACTION_FAILURE_DIAGNOSTIC,
    ]
    project["risk_domains"]["compaction"]["evidence"] = [
        "untrusted diagnostic",
        COMPACTION_FAILURE_DIAGNOSTIC,
    ]

    safe = build_remote_safe_report(payload)

    assert safe["projects"][0]["reasons"] == [
        "additional health signal omitted by remote privacy filter",
        COMPACTION_FAILURE_DIAGNOSTIC,
    ]
    assert safe["projects"][0]["risk_domains"]["compaction"]["evidence"] == [
        "additional health signal omitted by remote privacy filter",
        COMPACTION_FAILURE_DIAGNOSTIC,
    ]


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
        if command[:2] == ["sh", "-c"]:
            command = shlex.split(command[-1])
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
    report = fixture_remote_projects_report()
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
            "--remote-safe-json",
            "--progress",
            "never",
        ],
    ]
    common_runner_kwargs = {
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "check": False,
        "shell": False,
    }
    assert calls[0][1] == {**common_runner_kwargs, "timeout": 12}
    assert calls[1][1] == common_runner_kwargs


def test_run_remote_health_returns_version_drift_warning() -> None:
    report = fixture_remote_projects_report()
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


def test_run_remote_health_retries_through_remote_login_shell() -> None:
    report = fixture_remote_projects_report()
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                argv,
                127,
                stdout="",
                stderr="codex-thread-tools: command not found\n",
            )
        if len(calls) == 2:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="1.0.0\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(report),
            stderr="",
        )

    result = run_remote_health(
        "node1.atomicfalls.com",
        ["health", "projects"],
        local_version="1.0.0",
        runner=runner,
    )

    assert result == (report, 0, None)
    assert shlex.split(calls[0][0][-1]) == ["codex-thread-tools", "--version"]
    assert shlex.split(calls[1][0][-1]) == [
        "sh",
        "-c",
        'exec "${SHELL:-/bin/sh}" -lc "$1"',
        "codex-thread-tools-login",
        "codex-thread-tools --version",
    ]
    assert shlex.split(calls[2][0][-1]) == [
        "sh",
        "-c",
        'exec "${SHELL:-/bin/sh}" -lc "$1"',
        "codex-thread-tools-login",
        "codex-thread-tools health projects --remote-safe-json --progress never",
    ]


def test_run_remote_health_fails_closed_when_remote_lacks_safe_protocol() -> None:
    calls, runner = make_runner(
        fixture_projects_report(),
        version_stdout="1.1.0\n",
    )

    with pytest.raises(
        RemoteHealthError,
        match="privacy-safe remote health protocol",
    ):
        run_remote_health(
            "node1.atomicfalls.com",
            ["health", "projects"],
            local_version="1.0.0",
            runner=runner,
        )

    assert len(calls) == 2


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
        fixture_remote_projects_report(),
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

    assert len(calls) == (2 if version_returncode == 127 else 1)


def test_run_remote_health_maps_health_command_failure() -> None:
    calls, runner = make_runner(
        fixture_remote_projects_report(),
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
        fixture_remote_projects_report(),
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
        match=re.escape(
            "remote version probe timed out on node1.atomicfalls.com after 15 seconds"
        ),
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
        fixture_remote_projects_report(),
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
