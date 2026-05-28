"""Default local Codex session paths."""

from __future__ import annotations

from pathlib import Path


def default_session_root() -> Path:
    return Path("~/.codex/sessions").expanduser()


def default_quarantine_dir() -> Path:
    return Path("~/.codex/session_quarantine").expanduser()
