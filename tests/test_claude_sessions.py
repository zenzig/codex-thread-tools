from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()


def record(rtype: str, **fields: object) -> dict[str, object]:
    return {
        "type": rtype,
        "cwd": "/work/claude-project",
        "sessionId": "claude-session-1",
        "timestamp": "2026-09-23T10:00:00.000Z",
        **fields,
    }


def assistant(message_id: str, stop_reason: str, context_tokens: int) -> dict[str, object]:
    return record(
        "assistant",
        message={
            "id": message_id,
            "role": "assistant",
            "model": "claude-opus-5-5",
            "stop_reason": stop_reason,
            "content": [{"type": "text", "text": "Done."}],
            "usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": context_tokens,
                "output_tokens": 5,
            },
        },
    )


def write_session(path: Path) -> Path:
    records = [
        {"type": "file-history-snapshot", "snapshot": {}},
        record(
            "user",
            message={
                "role": "user",
                "content": [
                    {"type": "text", "text": "Fix the layout in this screenshot."},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}},
                ],
            },
        ),
        assistant("msg_1", "tool_use", 1_000),
        record(
            "user",
            message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
        ),
        assistant("msg_2", "end_turn", 2_000),
        record("system", subtype="turn_duration", durationMs=10),
        record(
            "system",
            subtype="compact_boundary",
            compactMetadata={"trigger": "auto", "preTokens": 150_000},
        ),
        record(
            "user",
            isCompactSummary=True,
            message={"role": "user", "content": "Summary of the earlier conversation."},
        ),
        record("user", message={"role": "user", "content": "Next step please."}),
        assistant("msg_3", "end_turn", 180_000),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item) + "\n" for item in records))
    return path


def run_tool(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
    )


def test_health_check_reads_claude_code_session(tmp_path: Path) -> None:
    session = write_session(tmp_path / "-work-claude-project" / "claude-session-1.jsonl")

    result = run_tool("tools/codex-thread-health.py", "check", str(session), "--json")

    payload = json.loads(result.stdout)
    metrics = payload["metrics"]
    assert payload["project"] == "/work/claude-project"
    assert payload["session_id"] == "claude-session-1"
    assert metrics["session_meta_records"] == 1
    assert metrics["context_compacted_events"] == 1
    assert metrics["installed_compaction_checkpoints"] == 1
    assert metrics["visual_embedded_artifacts"] == 1
    assert metrics["turn_complete_events"] == 2
    assert metrics["incomplete_turn_events"] == 0
    assert metrics["latest_active_token_total"] == 180_015
    assert metrics["latest_model_context_window"] == 200_000
    assert payload["risk_domains"]["limits"]["status"] == "danger"


def test_projects_scans_claude_root_and_skips_subagents(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    write_session(root / "-work-claude-project" / "claude-session-1.jsonl")
    write_session(
        root / "-work-claude-project" / "claude-session-1" / "subagents" / "agent-a1.jsonl"
    )

    result = run_tool(
        "tools/codex-thread-health.py",
        "projects",
        "--agent",
        "claude",
        "--session-root",
        str(root),
        "--json",
    )

    payload = json.loads(result.stdout)
    assert [item["file"].endswith("claude-session-1.jsonl") for item in payload["projects"]] == [True]


def test_visual_scan_finds_claude_screenshots(tmp_path: Path) -> None:
    session = write_session(tmp_path / "s" / "claude-session-1.jsonl")

    result = run_tool("tools/codex-visual-archive.py", "scan", str(session), "--json")

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert len(payload["artifacts"]) == 1


def test_install_skill_for_claude_code(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    env = {**os.environ, "HOME": str(tmp_path)}

    result = subprocess.run(
        ["node", str(ROOT / "bin" / "codex-thread-tools.js"), "install-skill", "--agent", "claude"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    installed = tmp_path / ".claude" / "skills" / "thread-handoff" / "SKILL.md"
    assert installed.read_text().startswith("---\nname: thread-handoff\n")


def test_reference_init_and_commit_stay_local(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    cli = ["node", str(ROOT / "bin" / "codex-thread-tools.js"), "reference"]

    init = subprocess.run([*cli, "init"], cwd=project, env=env, text=True, capture_output=True)
    (project / ".reference" / "docs" / "spec.md").write_text("# Spec\n")
    commit = subprocess.run(
        [*cli, "commit", "-m", "Add spec"], cwd=project, env=env, text=True, capture_output=True
    )

    assert init.returncode == 0, init.stderr
    assert commit.returncode == 0, commit.stderr
    assert "/.reference/" in (project / ".git" / "info" / "exclude").read_text()
    (project / "CLAUDE.local.md").write_text("Latest handoff: @.reference/handoffs/x.md\n")
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=project, text=True, capture_output=True
    )
    assert status.stdout == ""
    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=project / ".reference", text=True, capture_output=True
    )
    assert log.stdout.strip() == "Add spec"
