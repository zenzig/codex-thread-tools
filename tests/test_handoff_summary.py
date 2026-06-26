from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_summary(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "codex-thread-handoff-summary.py"), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_session(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )


def test_summary_keeps_durable_context_and_redacts_tool_payloads(tmp_path: Path) -> None:
    session = tmp_path / "summary.jsonl"
    write_session(
        session,
        [
            {
                "timestamp": "2026-06-26T10:00:00Z",
                "type": "session_meta",
                "payload": {"id": "summary-session", "cwd": "/work/summary"},
            },
            {
                "timestamp": "2026-06-26T10:01:00Z",
                "type": "turn_context",
                "payload": {"cwd": "/work/summary", "model": "gpt-5"},
            },
            {
                "timestamp": "2026-06-26T10:02:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Project fact: deploy target is staging. API key sk-test-secret",
                        }
                    ],
                },
            },
            {
                "timestamp": "2026-06-26T10:03:00Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": "SECRET_TOKEN=ghp_do_not_copy\nraw build log contents",
                },
            },
            {
                "timestamp": "2026-06-26T10:04:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Durable decision: use sidecar marker file for completed handoffs.",
                        }
                    ],
                },
            },
            {
                "timestamp": "2026-06-26T10:05:00Z",
                "type": "event_msg",
                "payload": {"type": "turn_complete", "message": "turn complete"},
            },
        ],
    )

    result = run_summary(str(session), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    rendered = json.dumps(payload)
    context = "\n".join(item["text"] for item in payload["durable_context"])
    assert payload["summary_type"] == "handoff_summary"
    assert payload["project"] == "/work/summary"
    assert payload["session_id"] == "summary-session"
    assert payload["pre_handoff_safety"]["status"] == "clean"
    assert "Project fact: deploy target is staging." in context
    assert "Durable decision: use sidecar marker file" in context
    assert "sk-test-secret" not in rendered
    assert "ghp_do_not_copy" not in rendered
    assert "raw build log contents" not in rendered
    assert "[REDACTED]" in rendered
    assert payload["redactions"]["tool_payloads_omitted"] == 1
    assert payload["visuals"]["archive_recommended"] == "not-needed"


def test_summary_flags_incomplete_turn_as_not_clean(tmp_path: Path) -> None:
    session = tmp_path / "incomplete-summary.jsonl"
    write_session(
        session,
        [
            {
                "timestamp": "2026-06-26T10:00:00Z",
                "type": "session_meta",
                "payload": {"id": "incomplete-summary", "cwd": "/work/incomplete-summary"},
            },
            {
                "timestamp": "2026-06-26T10:01:00Z",
                "type": "event_msg",
                "payload": {"type": "turn_started"},
            },
            {
                "timestamp": "2026-06-26T10:02:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Working on it."}],
                },
            },
        ],
    )

    result = run_summary(str(session), "--json")

    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["health"]["status"] == "warn"
    assert payload["pre_handoff_safety"]["status"] == "caution"
    assert payload["pre_handoff_safety"]["incomplete_turn_events"] == 1
    assert any("active turn" in reason for reason in payload["pre_handoff_safety"]["reasons"])


def test_pretty_summary_is_concise_and_human_readable(tmp_path: Path) -> None:
    session = tmp_path / "pretty-summary.jsonl"
    write_session(
        session,
        [
            {
                "timestamp": "2026-06-26T10:00:00Z",
                "type": "session_meta",
                "payload": {"id": "pretty-summary", "cwd": "/work/pretty-summary"},
            },
            {
                "timestamp": "2026-06-26T10:01:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Durable fact: keep README concise."}],
                },
            },
            {
                "timestamp": "2026-06-26T10:02:00Z",
                "type": "response_item",
                "payload": {"type": "function_call_output", "output": "large raw output"},
            },
            {
                "timestamp": "2026-06-26T10:03:00Z",
                "type": "event_msg",
                "payload": {"type": "turn_complete", "message": "turn complete"},
            },
        ],
    )

    result = run_summary(str(session))

    assert result.returncode == 0, result.stderr
    assert "Codex Thread Handoff Summary" in result.stdout
    assert "Pre-handoff safety: CLEAN" in result.stdout
    assert "- user: Durable fact: keep README concise." in result.stdout
    assert "Tool payloads omitted: 1" in result.stdout
    assert "large raw output" not in result.stdout
