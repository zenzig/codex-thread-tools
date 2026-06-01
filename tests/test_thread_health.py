from __future__ import annotations

import json
import base64
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "sessions"


def run_health(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "codex-thread-health.py"), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


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
    assert "Next step: Create a handoff" in result.stdout
    assert "/work/project-c" in result.stdout


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


def test_projects_progress_can_be_forced_to_stderr() -> None:
    result = run_health(
        "projects",
        "--session-root",
        str(FIXTURES),
        "--safe-test-mode",
        "--json",
        "--progress",
        "always",
        "--warn-items",
        "20",
        "--danger-items",
        "40",
    )

    assert result.returncode == 3
    json.loads(result.stdout)
    assert "Finding active sessions under:" in result.stderr
    assert "Analyzing 11 active project session(s)" in result.stderr
    assert "[1/11]" in result.stderr


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
    assert payload["risk_domains"]["visuals"]["status"] == "warn"
    assert any("visual" in reason for reason in payload["reasons"])


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
    assert "Domain risks:" in result.stdout
    assert "Continuation health: DANGER" in result.stdout
    assert "Handoff readiness: Needed" in result.stdout
    assert "Visuals: OK" in result.stdout
    assert "Compaction: DANGER" in result.stdout
    assert "Continuity: DANGER" in result.stdout


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
    assert "Reported lifetime tokens: 2353000" in result.stdout
    assert "/work/project-f" in result.stdout
    assert "Lifetime tokens: 2100000" in result.stdout
    assert "Active context: 15.48%" in result.stdout
