from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from codex_thread_tools import handoff_summary
from codex_thread_tools.redaction import redact_sensitive_text
from codex_thread_tools.thread_health import HealthThresholds, analyze_session_file

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


def test_summary_reuses_supplied_health_without_rescanning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = tmp_path / "summary.jsonl"
    write_session(
        session,
        [
            {
                "timestamp": "2026-06-26T10:00:00Z",
                "type": "session_meta",
                "payload": {"id": "summary-session", "cwd": "/work/summary"},
            }
        ],
    )
    health = analyze_session_file(session, HealthThresholds())

    def fail_if_called(*_args: object, **_kwargs: object) -> dict:
        raise AssertionError("health must be reused")

    monkeypatch.setattr(handoff_summary, "analyze_session_file", fail_if_called)

    summary = handoff_summary.build_handoff_summary(session, health=health)

    assert summary["session_id"] == "summary-session"


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
                            "text": "Project fact: deploy target is staging. API key " + "sk-" + "test-secret",
                        }
                    ],
                },
            },
            {
                "timestamp": "2026-06-26T10:03:00Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": "SECRET_TOKEN=" + "ghp_" + "do_not_copy\nraw build log contents",
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
    assert "sk-" + "test-secret" not in rendered
    assert "ghp_" + "do_not_copy" not in rendered
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


def test_redact_sensitive_text_slack_token_uppercase_suffix() -> None:
    value = "xoxb-" + "123456789012-1234567890123-ABCDefghIJKLm"
    plain_value = "xoxabcdefghijkl"

    redacted, count = redact_sensitive_text(value)
    assert "[REDACTED]" in redacted
    assert count == 1
    assert "ABCDefghIJKLm" not in redacted
    plain_redacted, plain_count = redact_sensitive_text(plain_value)
    assert plain_redacted == plain_value
    assert plain_count == 0


def test_redact_sensitive_text_long_format_values_dont_leak() -> None:
    long_auth = "Authorization: Bearer " + ("a" * 9000)
    long_uri = (
        "postgres://handoff_user:"
        + ("b" * 9000)
        + "@postgres.internal:5432/db?connect=true"
    )
    long_pem = (
        "-----BEGIN PRIVATE KEY-----\n"
        + ("c" * 50000)
        + "\n-----END PRIVATE KEY-----"
    )

    redacted_auth, auth_count = redact_sensitive_text(long_auth)
    redacted_uri, uri_count = redact_sensitive_text(long_uri)
    redacted_pem, pem_count = redact_sensitive_text(long_pem)

    assert redacted_auth == "Authorization: Bearer [REDACTED]"
    assert auth_count == 1

    assert "[REDACTED]" in redacted_uri
    assert "handoff_user" not in redacted_uri
    assert "b" * 9000 not in redacted_uri
    assert uri_count == 1

    assert "[REDACTED]" in redacted_pem
    assert "-----BEGIN PRIVATE KEY-----" not in redacted_pem
    assert "-----END PRIVATE KEY-----" not in redacted_pem
    assert "c" * 50000 not in redacted_pem
    assert pem_count == 1


def test_redact_sensitive_text_jwt_supports_short_segments() -> None:
    value = "eyJ0.e.f"

    redacted, count = redact_sensitive_text(value)
    assert "[REDACTED]" in redacted
    assert count == 1
    assert value not in redacted


def test_redact_sensitive_text_uri_with_no_userinfo_keeps_path_unchanged() -> None:
    value = "https://example.com:443/users/@me"

    redacted, count = redact_sensitive_text(value)
    assert redacted == value
    assert count == 0


def test_redact_sensitive_text_uri_userinfo_password_allows_colon_and_ampersand() -> None:
    value = "postgres://handoff_user:pass:word&and@postgres.internal/db"

    redacted, count = redact_sensitive_text(value)
    assert redacted == "postgres://[REDACTED]@postgres.internal/db"
    assert count == 1


def test_redact_sensitive_text_uri_userinfo_password_stops_at_delimiter_chars() -> None:
    values = (
        "postgres://handoff_user:super secret@postgres.internal/db",
        "postgres://handoff_user:super/secret@postgres.internal/db",
        "postgres://handoff_user:super?secret@postgres.internal/db",
        "postgres://handoff_user:super#secret@postgres.internal/db",
        "postgres://handoff_user:super@secret@postgres.internal/db",
    )

    for value in values:
        redacted, count = redact_sensitive_text(value)
        assert redacted == value
        assert count == 0


def test_redact_sensitive_text_single_secret_count_and_skip_already_redacted_assignment() -> None:
    value = "API_SECRET=[REDACTED]\nAPI_SECRET=[REDACTED]-actual-secret\nAPI_SECRET=already-[REDACTED]\n"

    redacted, count = redact_sensitive_text(value)
    assert count == 2
    assert "[REDACTED]" in redacted
    assert "API_SECRET=[REDACTED]-actual-secret" not in redacted
    assert "API_SECRET=already-[REDACTED]" not in redacted


def test_redact_sensitive_text_exact_redacted_assignment_not_counted() -> None:
    value = "API_SECRET=[REDACTED]\nAPI_SECRET=[REDACTED]-actual-secret"

    redacted, count = redact_sensitive_text(value)
    assert count == 1
    assert "API_SECRET=[REDACTED]" in redacted
    assert "[REDACTED]-actual-secret" not in redacted


def test_redact_sensitive_text_api_key_with_trailing_punctuation() -> None:
    for suffix in (".", "]", "}", ">", "`"):
        value = f"api-key=sk-abcdefghijklmnop{suffix}"
        redacted, count = redact_sensitive_text(value)
        assert redacted == f"api-key=[REDACTED]{suffix}"
        assert count == 1


def test_redact_sensitive_text_generic_values_keep_no_secret_punctuation() -> None:
    for value in ("password=!hunter2", "password=correct.horse"):
        redacted, count = redact_sensitive_text(value)
        assert redacted == "password=[REDACTED]"
        assert count == 1


def test_redact_sensitive_text_overlapping_rules_count_one_secret_once() -> None:
    value = "api-key=sk-abcdefghijklmnop"

    redacted, count = redact_sensitive_text(value)
    assert redacted == "api-key=[REDACTED]"
    assert count == 1


def test_redact_sensitive_text_export_keyword_preserved() -> None:
    value = "export SERVICE_PASSWORD=do-not-keep"

    redacted, count = redact_sensitive_text(value)
    assert redacted == "export SERVICE_PASSWORD=[REDACTED]"
    assert count == 1


def test_redact_sensitive_text_quotes_json_and_yaml_style_credentials() -> None:
    values = (
        '"password": "hunter2"',
        "'client_secret': 'value'",
    )
    for value in values:
        redacted, count = redact_sensitive_text(value)
        if value.startswith("'"):
            assert redacted.endswith("'[REDACTED]'")
        else:
            assert redacted.endswith("\"[REDACTED]\"")
        assert count == 1


def test_redact_sensitive_text_compact_json_credentials() -> None:
    value = '{"password":"hunter2","safe":"visible","client_secret":"value"}'

    redacted, count = redact_sensitive_text(value)

    assert redacted == (
        '{"password":"[REDACTED]","safe":"visible",'
        '"client_secret":"[REDACTED]"}'
    )
    assert count == 2


def test_redact_sensitive_text_query_parameters_keep_delimiters() -> None:
    value = "https://api.example.com/cb?access_token=abc123&client_secret=def456&scope=read"
    redacted, count = redact_sensitive_text(value)
    assert redacted == "https://api.example.com/cb?access_token=[REDACTED]&client_secret=[REDACTED]&scope=read"
    assert count == 2


def test_redact_sensitive_text_rejects_repeated_secret_keywords_without_assignment() -> None:
    value = (
        "token secret password api_key access_token credential "
        "password token api secret key"
    )
    redacted, count = redact_sensitive_text(value)
    assert redacted == value
    assert count == 0


def test_redact_sensitive_text_compound_labels_cover_compound_words_and_query_parameters() -> None:
    cases = (
        ("api_secret=old_secret", "MYSECRET=old_secret"),
        ('{"refreshToken":"abc123","monkey":"safe"}', "monkey"),
        (
            "https://example.test/cb?refreshToken=abc123&api_secret=do-not-share&monkey=safe",
            "abc123",
        ),
    )
    for value in (
        "MYSECRET=old_secret",
        "MYAPIKEY=old_key",
        "api_secret=do-not-share",
        "refreshToken=mySecret",
        "github_token=github-secret",
        "oauthToken=oauth-secret",
        "id_token=id-secret",
        "personalAccessToken=personal-secret",
    ):
        redacted, count = redact_sensitive_text(value)
        assert "[REDACTED]" in redacted
        assert count == 1
        assert "do-not-share" not in redacted
        assert "mySecret" not in redacted
        assert "old_secret" not in redacted
        assert "old_key" not in redacted
        assert "github-secret" not in redacted
        assert "oauth-secret" not in redacted
        assert "id-secret" not in redacted
        assert "personal-secret" not in redacted

    json_case, _normal_key = cases[1]
    redacted, count = redact_sensitive_text(json_case)
    assert redacted == (
        '{"refreshToken":"[REDACTED]","monkey":"safe"}'
    )
    assert count == 1

    query_case, leaked = cases[2]
    redacted, count = redact_sensitive_text(query_case)
    assert redacted == (
        "https://example.test/cb?refreshToken=[REDACTED]&"
        "api_secret=[REDACTED]&monkey=safe"
    )
    assert count == 2
    assert leaked not in redacted


def test_redact_sensitive_text_compound_labels_do_not_match_plain_words() -> None:
    value = "https://example.test/api?monkey=curious&token_stream=open"
    redacted, count = redact_sensitive_text(value)

    assert redacted == value
    assert count == 0


def test_redact_sensitive_text_punctuation_only_secret_values_do_not_crash() -> None:
    value = "token=}"
    redacted, count = redact_sensitive_text(value)

    assert redacted == "token=[REDACTED]"
    assert count == 1


def test_redact_sensitive_text_quoted_value_with_escaped_quote_keeps_no_suffix_exposure() -> None:
    value = 'API_SECRET="abc\\"def"'
    redacted, count = redact_sensitive_text(value)

    assert redacted == 'API_SECRET="[REDACTED]"'
    assert count == 1
    assert "abc" not in redacted
    assert '\\"' not in redacted


def test_redact_sensitive_text_table_driven() -> None:
    aws_key = "AKIA" + "1234567890ABCDEF"
    openai_key = "sk-" + "abcdefghijklmnopqrstuVWX"
    github_token = "ghp_" + "abcdefghijklmnopqrstuvwxyz1234"
    anthropic_key = "sk-ant-" + "api03-prod-abcdefghijklmnopqrstuvwxyz1234"
    stripe_key = "sk_" + "live_abcdefghijklmnopqrstuvwxyz1234"
    stripe_recovery_key = "rk_" + "live_abcdefghijklmnopqrstuvwxyz1234"
    gitlab_token = "glpat-" + "abcdefghijklmnopqrstuvwxyz1234"
    npm_token = "npm_" + "1234567890abcdefghijklmno"
    slack_token = "xoxb-" + "123456789012-1234567890123-ABCDEFGHIJKLMNOP"
    sensitive_cases = (
        ("AWS access key", aws_key, aws_key),
        (
            "Bearer JWT",
            "Authorization: Bearer eyJ0ZXN0LmhlYWRlci5zaWduYXR1cmU.eyJwYXlsb2FkIn0.signature",
            "eyJ0ZXN0LmhlYWRlci5zaWduYXR1cmU.eyJwYXlsb2FkIn0.signature",
        ),
        ("Basic auth", "Authorization: Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==", "QWxhZGRpbjpvcGVuIHNlc2FtZQ=="),
        (
            "Postgres URI credentials",
            "postgres://handoff_user:super_secret@postgres.internal:5432/app?sslmode=require",
            "super_secret",
        ),
        ("OpenAI key", "openai_key=" + openai_key, openai_key),
        ("GitHub token", github_token, github_token),
        ("Anthropic key", anthropic_key, anthropic_key),
        ("Stripe key", stripe_key, stripe_key),
        ("Stripe recovery key", stripe_recovery_key, stripe_recovery_key),
        ("GitLab token", gitlab_token, gitlab_token),
        ("npm token", npm_token, npm_token),
        ("Slack token", slack_token, slack_token),
        ("JWT", "eyJ0ZXN0LmFoZWE.eyJwYXlsb2FkIn0.Zm9vYmFy", "eyJ0ZXN0LmFoZWE.eyJwYXlsb2FkIn0.Zm9vYmFy"),
        ("Labeled assignment", "api-key=mysecretvalue", "mysecretvalue"),
        ("Shell assignment", "export SERVICE_PASSWORD=do-not-keep", "do-not-keep"),
        ("Auth assignment", "REGISTRY_AUTH=do-not-keep", "do-not-keep"),
    )

    for label, value, secret in sensitive_cases:
        redacted, count = redact_sensitive_text(value)
        assert "[REDACTED]" in redacted, label
        assert count == 1, label
        assert secret not in redacted, label


def test_redact_sensitive_text_multiline_pem() -> None:
    pem_text = (
        "-----BEGIN PRIVATE KEY-----\n"
        "QUJDREVGSElKS0xNTk9Q\n"
        "UVdYWFpaW0FCQkNERUZH\n"
        "-----END PRIVATE KEY-----\n"
        "Use this credential only at startup."
    )

    redacted, count = redact_sensitive_text(pem_text)
    assert count == 1
    assert "-----BEGIN PRIVATE KEY-----" not in redacted
    assert "-----END PRIVATE KEY-----" not in redacted
    assert "QUJDREVG" not in redacted
    assert "startup" in redacted
    assert "[REDACTED]" in redacted


def test_redact_sensitive_text_pem_blocks_dont_cross_nested_begin() -> None:
    value = (
        "pre\n"
        "-----BEGIN PRIVATE KEY-----\n"
        "outer\n"
        "-----BEGIN PRIVATE KEY-----\n"
        "inner\n"
        "-----END PRIVATE KEY-----\n"
        "outer-tail\n"
        "-----END PRIVATE KEY-----\n"
    )

    redacted, count = redact_sensitive_text(value)
    assert count == 1
    assert "-----BEGIN PRIVATE KEY-----" not in redacted
    assert "outer\n" not in redacted
    assert "inner\n" not in redacted
    assert "outer-tail" not in redacted
    assert "inner" not in redacted


def test_redact_sensitive_text_pem_redacts_unmatched_begin_through_eof() -> None:
    value = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "unmatched outer\n"
        "-----BEGIN PRIVATE KEY-----\n"
        "inner secret\n"
        "-----END PRIVATE KEY-----\n"
    )

    redacted, count = redact_sensitive_text(value)
    assert count == 1
    assert "-----BEGIN RSA PRIVATE KEY-----" not in redacted
    assert "unmatched outer" not in redacted
    assert "inner secret" not in redacted


def test_redact_sensitive_text_safe_cases() -> None:
    safe_cases = (
        "https://example.com/public?asset=logo.png",
        "The token stream for the parser can be long.",
        "ACaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
    )

    for value in safe_cases:
        redacted, count = redact_sensitive_text(value)
        assert redacted == value
        assert count == 0


def test_durable_context_keeps_text_around_pem_and_normalizes(tmp_path: Path) -> None:
    session = tmp_path / "summary-pem-ctx.jsonl"
    write_session(
        session,
        [
            {
                "timestamp": "2026-06-26T10:00:00Z",
                "type": "session_meta",
                "payload": {"id": "summary-pem", "cwd": "/work/summary"},
            },
            {
                "timestamp": "2026-06-26T10:01:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                "Bootstrap key material:\n"
                                "-----BEGIN RSA PRIVATE KEY-----\n"
                                "QUJDREVGSElKS0xNTk9Q\n"
                                "-----END RSA PRIVATE KEY-----\n"
                                "Rotate it after deploy.\n"
                            ),
                        }
                    ],
                },
            },
            {
                "timestamp": "2026-06-26T10:02:00Z",
                "type": "event_msg",
                "payload": {"type": "turn_complete", "message": "turn complete"},
            },
        ],
    )

    result = run_summary(str(session), "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    context = payload["durable_context"][0]["text"]

    assert "-----BEGIN RSA PRIVATE KEY-----" not in context
    assert "-----END RSA PRIVATE KEY-----" not in context
    assert "Rotate it after deploy." in context
    assert "QUJDREVG" not in context
    assert payload["redactions"]["sensitive_values_redacted"] == 1
