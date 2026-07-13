from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from codex_thread_tools.handoff_markers import marker_aware_active_sessions_by_project


ROOT = Path(__file__).resolve().parents[1]


def write_session(
    path: Path,
    *,
    session_id: str,
    project: str,
    thread_source: str | None = None,
    parent_thread_id: str | None = None,
    mtime: float,
) -> None:
    payload = {"id": session_id, "cwd": project}
    if thread_source is not None:
        payload["thread_source"] = thread_source
    if parent_thread_id is not None:
        payload["parent_thread_id"] = parent_thread_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"type": "session_meta", "payload": payload}) + "\n",
        encoding="utf-8",
    )
    os.utime(path, (mtime, mtime))


def test_project_selection_prefers_root_thread_over_newer_subagent(
    tmp_path: Path,
) -> None:
    project = "/work/project"
    parent = tmp_path / "parent.jsonl"
    child = tmp_path / "child.jsonl"
    write_session(
        parent,
        session_id="parent",
        project=project,
        thread_source="user",
        mtime=100,
    )
    write_session(
        child,
        session_id="child",
        project=project,
        thread_source="subagent",
        parent_thread_id="parent",
        mtime=200,
    )

    assert marker_aware_active_sessions_by_project(tmp_path, []) == [parent]


def test_project_selection_treats_parentless_migrated_subagent_as_root(
    tmp_path: Path,
) -> None:
    project = "/work/project"
    migrated_root = tmp_path / "migrated-root.jsonl"
    child = tmp_path / "child.jsonl"
    write_session(
        migrated_root,
        session_id="parent",
        project=project,
        thread_source="subagent",
        mtime=100,
    )
    write_session(
        child,
        session_id="child",
        project=project,
        thread_source="subagent",
        parent_thread_id="parent",
        mtime=200,
    )

    assert marker_aware_active_sessions_by_project(tmp_path, []) == [migrated_root]


def test_project_selection_prefers_root_thread_over_newer_automation(
    tmp_path: Path,
) -> None:
    project = "/work/project"
    parent = tmp_path / "parent.jsonl"
    automation = tmp_path / "automation.jsonl"
    write_session(
        parent,
        session_id="parent",
        project=project,
        thread_source="user",
        mtime=100,
    )
    write_session(
        automation,
        session_id="automation",
        project=project,
        thread_source="automation",
        mtime=200,
    )

    assert marker_aware_active_sessions_by_project(tmp_path, []) == [parent]


def test_project_selection_uses_newest_root_and_falls_back_to_newest_child(
    tmp_path: Path,
) -> None:
    root_project = "/work/root-project"
    child_project = "/work/child-only-project"
    old_root = tmp_path / "old-root.jsonl"
    new_root = tmp_path / "new-root.jsonl"
    old_child = tmp_path / "old-child.jsonl"
    new_child = tmp_path / "new-child.jsonl"
    write_session(
        old_root,
        session_id="old-root",
        project=root_project,
        thread_source="user",
        mtime=100,
    )
    write_session(
        new_root,
        session_id="new-root",
        project=root_project,
        thread_source="user",
        mtime=200,
    )
    write_session(
        old_child,
        session_id="old-child",
        project=child_project,
        thread_source="subagent",
        parent_thread_id="missing-parent",
        mtime=300,
    )
    write_session(
        new_child,
        session_id="new-child",
        project=child_project,
        thread_source="subagent",
        parent_thread_id="missing-parent",
        mtime=400,
    )

    assert marker_aware_active_sessions_by_project(tmp_path, []) == [
        new_child,
        new_root,
    ]


def run_marker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "codex-thread-handoff-marker.py"), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_record_handoff_marker_increments_project_sequence(tmp_path: Path) -> None:
    marker_file = tmp_path / "markers" / "handoff-markers.jsonl"
    session_file = tmp_path / "session.jsonl"
    replacement_file = tmp_path / "replacement.jsonl"
    handoff_one = tmp_path / "handoff-one.md"
    handoff_two = tmp_path / "handoff-two.md"
    project = "/work/project"
    session_file.write_text(
        json.dumps(
            {
                "timestamp": "2026-06-03T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "source-one", "cwd": project},
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    replacement_file.write_text(
        json.dumps(
            {
                "timestamp": "2026-06-03T12:30:00Z",
                "type": "session_meta",
                "payload": {"id": "replacement-one", "cwd": project},
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    first = run_marker(
        "record",
        "--marker-file",
        str(marker_file),
        "--source-session-file",
        str(session_file),
        "--replacement-session-file",
        str(replacement_file),
        "--handoff-file",
        str(handoff_one),
        "--created-at",
        "2026-06-03T12:00:00Z",
    )
    second = run_marker(
        "record",
        "--marker-file",
        str(marker_file),
        "--project",
        project,
        "--source-session-id",
        "source-two",
        "--source-session-file",
        str(session_file),
        "--handoff-file",
        str(handoff_two),
        "--created-at",
        "2026-06-03T13:00:00Z",
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "Codex thread handoff marker:" in second.stdout
    assert "source_session_id: source-two" in second.stdout
    records = [
        json.loads(line)
        for line in marker_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [record["handoff_sequence"] for record in records] == [1, 2]
    assert records[0]["project"] == project
    assert records[0]["source_session_id"] == "source-one"
    assert records[0]["replacement_session_id"] == "replacement-one"
    assert records[0]["replacement_session_file"] == str(replacement_file)
    assert records[1]["handoff_file"] == str(handoff_two)
