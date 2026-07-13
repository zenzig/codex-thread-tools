"""SSH transport for remote Codex thread health reports."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from copy import deepcopy
from typing import Any, Callable


class RemoteHealthError(ValueError):
    """Expected remote-health operational failure."""


Runner = Callable[..., subprocess.CompletedProcess[str]]

VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SUMMARY_KEYS = ("projects", "ok", "warn", "danger", "retired")
PROJECT_KEYS = (
    "project",
    "status",
    "recommendation",
    "metrics",
    "reasons",
    "handoff_readiness",
)


def build_ssh_argv(
    host: str,
    remote_args: list[str],
    *,
    connect_timeout: int = 10,
    ssh_executable: str = "ssh",
) -> list[str]:
    if not host or host.startswith("-"):
        raise RemoteHealthError("SSH host must be a non-empty destination")
    if connect_timeout < 1:
        raise RemoteHealthError("SSH connection timeout must be at least 1 second")
    return [
        ssh_executable,
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "--",
        host,
        shlex.join(remote_args),
    ]


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(value.strip())
    if not match:
        raise RemoteHealthError(f"invalid version returned by remote host: {value!r}")
    return tuple(int(part) for part in match.groups())


def ensure_compatible_versions(local_version: str, remote_version: str) -> str | None:
    local = _version_tuple(local_version)
    remote = _version_tuple(remote_version)
    if local[0] != remote[0]:
        raise RemoteHealthError(
            "incompatible remote version: "
            f"local {local_version}, remote {remote_version}; install matching major versions"
        )
    if local != remote:
        return f"remote version differs: local {local_version}, remote {remote_version}"
    return None


def validate_projects_report(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RemoteHealthError("invalid remote health report: expected a JSON object")
    if not isinstance(value.get("session_root"), str):
        raise RemoteHealthError("invalid remote health report: missing session_root")
    summary = value.get("summary")
    if not isinstance(summary, dict) or any(
        not isinstance(summary.get(key), int) for key in SUMMARY_KEYS
    ):
        raise RemoteHealthError("invalid remote health report: invalid summary")
    projects = value.get("projects")
    if not isinstance(projects, list):
        raise RemoteHealthError("invalid remote health report: projects must be a list")
    for project in projects:
        if not isinstance(project, dict) or any(key not in project for key in PROJECT_KEYS):
            raise RemoteHealthError("invalid remote health report: invalid project entry")
    return value


def _remote_stderr(result: subprocess.CompletedProcess[str]) -> str:
    value = result.stderr or ""
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    return str(value).strip()[:500]


def _run_ssh(
    host: str,
    remote_args: list[str],
    *,
    connect_timeout: int,
    ssh_executable: str,
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    argv = build_ssh_argv(
        host,
        remote_args,
        connect_timeout=connect_timeout,
        ssh_executable=ssh_executable,
    )
    try:
        return runner(
            argv,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
            timeout=connect_timeout + 5,
        )
    except FileNotFoundError as exc:
        raise RemoteHealthError(
            f"SSH executable was not found: {ssh_executable}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RemoteHealthError(
            f"SSH connection to {host} timed out"
        ) from exc


def _raise_remote_command_error(
    result: subprocess.CompletedProcess[str],
    host: str,
    *,
    command: str,
) -> None:
    if result.returncode == 255:
        raise RemoteHealthError(
            f"SSH command failed for {host}: {_remote_stderr(result)}"
        )
    if result.returncode == 127:
        raise RemoteHealthError(
            "remote codex-thread-tools is not installed or not available to "
            f"non-interactive SSH on {host}"
        )
    raise RemoteHealthError(
        f"remote {command} command failed on {host}: {_remote_stderr(result)}"
    )


def run_remote_health(
    host: str,
    remote_args: list[str],
    *,
    local_version: str,
    connect_timeout: int = 10,
    ssh_executable: str = "ssh",
    runner: Runner = subprocess.run,
) -> tuple[dict[str, Any], int, str | None]:
    version_result = _run_ssh(
        host,
        ["codex-thread-tools", "--version"],
        connect_timeout=connect_timeout,
        ssh_executable=ssh_executable,
        runner=runner,
    )
    if version_result.returncode != 0:
        _raise_remote_command_error(version_result, host, command="version")
    remote_version = version_result.stdout.strip()
    warning = ensure_compatible_versions(local_version, remote_version)

    health_args = deepcopy(remote_args)
    health_args.extend(("--json", "--progress", "never"))
    health_result = _run_ssh(
        host,
        ["codex-thread-tools", *health_args],
        connect_timeout=connect_timeout,
        ssh_executable=ssh_executable,
        runner=runner,
    )
    if health_result.returncode not in {0, 2, 3}:
        _raise_remote_command_error(health_result, host, command="health")

    try:
        report = json.loads(health_result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RemoteHealthError(
            f"remote health command returned malformed JSON from {host}"
        ) from exc
    return validate_projects_report(report), health_result.returncode, warning
