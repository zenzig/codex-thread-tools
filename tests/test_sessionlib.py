from __future__ import annotations

import subprocess
from pathlib import Path

import codex_thread_tools
from codex_thread_tools import sessionlib


ROOT = Path(__file__).resolve().parents[1]


def test_package_version_matches_version_file() -> None:
    assert codex_thread_tools.__version__ == (ROOT / "VERSION").read_text(
        encoding="utf-8"
    ).strip()


def test_process_listing_command_uses_no_platform_app_paths() -> None:
    for system in ("Darwin", "Linux", "Windows"):
        command = " ".join(sessionlib.process_listing_command(system))
        assert "Codex" not in command
        assert "Applications" not in command
        assert "Contents" not in command


def test_process_line_looks_like_codex_matches_process_names_only() -> None:
    assert sessionlib.process_line_looks_like_codex(
        '"Codex.exe","1234","Console","1","100,000 K"'
    )
    assert sessionlib.process_line_looks_like_codex("Codex Helper")
    assert not sessionlib.process_line_looks_like_codex(
        "python tools/recover-codex-thread-starter.py"
    )
    assert not sessionlib.process_line_looks_like_codex(
        "/Users/example/code/codex-thread-tools"
    )


def test_is_codex_running_uses_platform_process_listing(monkeypatch) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = '"Codex.exe","1234","Console","1","100,000 K"\n'

    monkeypatch.setattr(sessionlib.platform, "system", lambda: "Windows")

    def fake_run(command, **kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert sessionlib.is_codex_running()
    assert calls == [["tasklist", "/FO", "CSV", "/NH"]]
