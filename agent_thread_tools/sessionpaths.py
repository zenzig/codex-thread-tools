"""Default local session paths for Codex and Claude Code."""

from __future__ import annotations

from pathlib import Path

AGENTS = ("codex", "claude")


def codex_session_root() -> Path:
    return Path("~/.codex/sessions").expanduser()


def claude_session_root() -> Path:
    return Path("~/.claude/projects").expanduser()


def default_agent() -> str:
    """Codex when its session root exists, otherwise Claude Code when present."""
    if not codex_session_root().exists() and claude_session_root().exists():
        return "claude"
    return "codex"


def default_session_root(agent: str | None = None) -> Path:
    if (agent or default_agent()) == "claude":
        return claude_session_root()
    return codex_session_root()


def default_quarantine_dir() -> Path:
    return Path("~/.codex/session_quarantine").expanduser()


def iter_session_paths(session_root: Path):
    """Session JSONL files under a root, skipping Claude Code subagent transcripts."""
    for path in session_root.rglob("*.jsonl"):
        if "subagents" not in path.relative_to(session_root).parts:
            yield path
