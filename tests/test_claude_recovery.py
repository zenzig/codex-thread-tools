from __future__ import annotations

import base64
import json
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
GOOD_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()
BROKEN = "not-base64!!"


def run_recover(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "recover-codex-thread-starter.py"), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def image(data: str) -> dict[str, object]:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}


def record(rtype: str, content: object, **fields: object) -> dict[str, object]:
    return {
        "type": rtype,
        "cwd": "/work/claude-project",
        "sessionId": "claude-1",
        "timestamp": "2026-09-23T10:00:00.000Z",
        "message": {"role": rtype, "content": content},
        **fields,
    }


def write_claude_session(path: Path, *, pasted: str = GOOD_PNG, tool_image: str = BROKEN) -> Path:
    records = [
        record("user", [{"type": "text", "text": "look at this"}, image(pasted)]),
        record("assistant", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]),
        record(
            "user",
            [{"type": "tool_result", "tool_use_id": "t1", "content": [image(tool_image)]}],
        ),
        record("assistant", [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {}}]),
        record("user", [{"type": "text", "text": "next question"}]),
    ]
    path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
    return path


def test_inspect_summarizes_a_claude_session(tmp_path: Path) -> None:
    session = write_claude_session(tmp_path / "claude-1.jsonl")

    result = run_recover("inspect", str(session))

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["agent"] == "claude"
    assert summary["images"] == 2
    assert summary["tool_uses"] == 2
    assert summary["tool_results"] == 1


def test_diagnose_flags_broken_images_and_unanswered_tool_calls(tmp_path: Path) -> None:
    session = write_claude_session(tmp_path / "claude-1.jsonl")

    result = run_recover("diagnose", "--json", str(session))

    assert result.returncode == 3, result.stderr
    diagnosis = json.loads(result.stdout)
    assert diagnosis["agent"] == "claude"
    assert diagnosis["status"] == "danger"
    assert diagnosis["recommended_action"] == "strip-images"
    assert diagnosis["integrity"]["invalid_image_urls"] == 1
    assert diagnosis["claude"]["tool_calls_without_results"] == 1


def test_strip_images_replaces_only_broken_images(tmp_path: Path) -> None:
    session = write_claude_session(tmp_path / "claude-1.jsonl")
    output = tmp_path / "repaired.jsonl"

    result = run_recover("strip-images", str(session), "--output", str(output))

    assert result.returncode == 0, result.stderr
    assert "images_replaced: 1" in result.stdout
    source_lines = session.read_text(encoding="utf-8").splitlines()
    repaired_lines = output.read_text(encoding="utf-8").splitlines()
    assert len(repaired_lines) == len(source_lines)
    assert repaired_lines[0] == source_lines[0]
    assert BROKEN not in output.read_text(encoding="utf-8")
    assert GOOD_PNG in output.read_text(encoding="utf-8")
    assert run_recover("diagnose", "--json", str(output)).returncode != 3


def test_strip_images_all_replaces_every_image(tmp_path: Path) -> None:
    session = write_claude_session(tmp_path / "claude-1.jsonl", tool_image=GOOD_PNG)
    output = tmp_path / "repaired.jsonl"

    refused = run_recover("strip-images", str(session), "--output", str(output))
    assert refused.returncode == 1
    assert "no broken images found" in refused.stderr
    assert not output.exists()

    result = run_recover("strip-images", "--all", str(session), "--output", str(output))
    assert result.returncode == 0, result.stderr
    assert "images_replaced: 2" in result.stdout
    assert GOOD_PNG not in output.read_text(encoding="utf-8")


@pytest.mark.parametrize("command", ["strip-compacted", "rebuild-window"])
def test_codex_only_repairs_refuse_claude_sessions(tmp_path: Path, command: str) -> None:
    session = write_claude_session(tmp_path / "claude-1.jsonl")
    extra = ["--start", "2026-01-01", "--end", "2027-01-01"] if command == "rebuild-window" else []

    result = run_recover(command, str(session), "--output", str(tmp_path / "out.jsonl"), *extra)

    assert result.returncode == 1
    assert "does not apply to Claude Code sessions" in result.stderr


def test_writes_are_refused_while_the_claude_session_is_open(tmp_path: Path, monkeypatch) -> None:
    spec = spec_from_file_location("recover_claude_test", ROOT / "tools" / "recover-codex-thread-starter.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    session = write_claude_session(tmp_path / "claude-1.jsonl")
    monkeypatch.setattr(module, "open_claude_sessions", lambda: {"claude-1"})

    with pytest.raises(SystemExit, match="open in Claude Code"):
        module.backup_command(
            SimpleNamespace(
                session_file=str(session),
                backup_dir=str(tmp_path / "backups"),
                allow_codex_running=False,
            )
        )
    assert not (tmp_path / "backups").exists()


def test_bundle_for_a_claude_session_points_to_claude_code(tmp_path: Path) -> None:
    session = write_claude_session(tmp_path / "claude-1.jsonl")
    project = tmp_path / "project"
    project.mkdir()

    result = run_recover(
        "bundle",
        str(session),
        "--project-root",
        str(project),
        "--output-root",
        str(tmp_path / "bundles"),
    )

    assert result.returncode == 0, result.stderr
    [bundle] = [path for path in (tmp_path / "bundles").iterdir() if path.is_dir()]
    prompt = (bundle / "fresh-task-prompt.md").read_text(encoding="utf-8")
    assert "Start a new Claude Code session" in prompt
