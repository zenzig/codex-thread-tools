from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
