#!/usr/bin/env python3
"""Set up and commit a project's local-only `.reference/` git repository."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REFERENCE_DIR = ".reference"
LOCAL_ONLY_ENTRIES = (f"/{REFERENCE_DIR}/", "/CLAUDE.local.md")
INDEX_TEMPLATE = "# Reference Index\n\nOne line per saved document or screenshot set.\n"


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=False
    )


def project_root(start: Path) -> Path:
    result = git(start, "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()) if result.returncode == 0 else start


def exclude_from_project(root: Path) -> str:
    """Hide local-only files from the project repository without editing tracked files."""
    result = git(root, "rev-parse", "--git-path", "info/exclude")
    if result.returncode != 0:
        return "project is not a git repository"
    exclude = (root / result.stdout.strip()).resolve()
    lines = exclude.read_text().splitlines() if exclude.exists() else []
    missing = [entry for entry in LOCAL_ONLY_ENTRIES if entry not in lines]
    if not missing:
        return f"already excluded in {exclude}"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a") as handle:
        handle.writelines(f"{entry}\n" for entry in missing)
    return f"excluded {', '.join(missing)} in {exclude}"


def init(root: Path) -> Path:
    reference = root / REFERENCE_DIR
    for sub in ("handoffs", "docs"):
        (reference / sub).mkdir(parents=True, exist_ok=True)
    index = reference / "INDEX.md"
    if not index.exists():
        index.write_text(INDEX_TEMPLATE)
    if not (reference / ".git").exists():
        git(reference, "init", "-q")
    print(f"Reference repository: {reference}")
    print(f"Project repository: {exclude_from_project(root)}")
    return reference


def commit(reference: Path, message: str) -> int:
    git(reference, "add", "-A")
    if git(reference, "diff", "--cached", "--quiet").returncode == 0:
        print("Nothing new to commit in the reference repository")
        return 0
    result = git(reference, "commit", "-q", "-m", message)
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        return 1
    print(f"Committed to {reference}: {message}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create or commit a project's local-only .reference/ git repository."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "commit"):
        command = sub.add_parser(name)
        command.add_argument(
            "--project",
            default=".",
            help="project directory (default: current)",
        )
        if name == "commit":
            command.add_argument("-m", "--message", default="Update reference material")
    args = parser.parse_args(argv)
    root = project_root(Path(args.project).expanduser().resolve())
    reference = init(root)
    if args.command == "commit":
        return commit(reference, args.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
