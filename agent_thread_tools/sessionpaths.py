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


def claude_session_registry() -> Path:
    """Claude Code writes one ``<pid>.json`` here for each open session."""
    return Path("~/.claude/sessions").expanduser()


def companion_dir(session_file: Path) -> Path:
    """The folder Claude Code keeps beside ``<id>.jsonl`` (subagents, tool results)."""
    return session_file.with_suffix("")


def companion_files(session_file: Path) -> list[Path]:
    folder = companion_dir(session_file)
    if not folder.is_dir() or folder.is_symlink():
        return []
    return sorted(path for path in folder.rglob("*") if path.is_file() and not path.is_symlink())


def iter_session_paths(session_root: Path):
    """Session JSONL files under a root, skipping files inside a session's own folder."""
    for path in session_root.rglob("*.jsonl"):
        parts = path.relative_to(session_root).parts
        if "subagents" in parts:
            continue
        ancestors = [session_root.joinpath(*parts[:depth]) for depth in range(1, len(parts))]
        if any(folder.with_suffix(".jsonl").is_file() for folder in ancestors):
            continue
        yield path
