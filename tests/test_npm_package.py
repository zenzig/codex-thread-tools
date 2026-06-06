from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_package_metadata_is_publish_ready() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert package["name"] == "codex-thread-tools"
    assert package["version"] == (ROOT / "VERSION").read_text(
        encoding="utf-8"
    ).strip()
    assert (
        package["description"]
        == "CLI health checks, handoffs, visual archives, and recovery tools for OpenAI Codex session threads."
    )
    assert package["author"] == "Rich Olson"
    assert package["bin"]["codex-thread-tools"] == "bin/codex-thread-tools.js"
    assert package["license"] == "MIT"
    assert "codex" in package["keywords"]
    assert "openai-codex" in package["keywords"]
    assert "tests/" not in package["files"]
    assert "docs/" not in package["files"]


def test_npm_cli_help_and_version() -> None:
    help_result = subprocess.run(
        ["node", str(ROOT / "bin" / "codex-thread-tools.js"), "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    version_result = subprocess.run(
        ["node", str(ROOT / "bin" / "codex-thread-tools.js"), "--version"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert help_result.returncode == 0, help_result.stderr
    assert "codex-thread-tools" in help_result.stdout
    assert "health [args...]" in help_result.stdout
    assert "install-skill" in help_result.stdout
    assert version_result.returncode == 0, version_result.stderr
    assert version_result.stdout.strip() == (ROOT / "VERSION").read_text(
        encoding="utf-8"
    ).strip()


def test_npm_cli_dispatches_health_tool() -> None:
    result = subprocess.run(
        [
            "node",
            str(ROOT / "bin" / "codex-thread-tools.js"),
            "health",
            "check",
            "--help",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "codex-thread-health.py check" in result.stdout
    assert "session_file" in result.stdout


def test_npm_cli_uses_only_first_available_python(tmp_path: Path) -> None:
    call_log = tmp_path / "python-calls.log"
    for name in ("python3", "python"):
        executable = tmp_path / name
        executable.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    f"printf '%s\\n' '{name}' >> \"$CALL_LOG\"",
                    f"printf '%s\\n' '{name} invoked'",
                    "exit 0",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        executable.chmod(0o755)

    env = os.environ.copy()
    env["CALL_LOG"] = str(call_log)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["node", str(ROOT / "bin" / "codex-thread-tools.js"), "health"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "python3 invoked\n"
    assert call_log.read_text(encoding="utf-8").splitlines() == ["python3"]


def test_npm_pack_excludes_generated_and_local_artifacts() -> None:
    result = subprocess.run(
        ["npm", "pack", "--dry-run", "--json"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    [package] = json.loads(result.stdout)
    paths = {entry["path"] for entry in package["files"]}
    assert all("__pycache__" not in path for path in paths)
    assert all(not path.startswith("tests/") for path in paths)
    assert all(not path.startswith("documentation/") for path in paths)
    assert "bin/codex-thread-tools.js" in paths
    assert "codex_thread_tools/thread_health.py" in paths
    assert "tools/codex-thread-health.py" in paths
