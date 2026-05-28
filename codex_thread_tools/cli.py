"""Argparse helpers shared by codex-thread-tools command-line tools."""

from __future__ import annotations

import argparse


def add_common_args(
    subparser: argparse.ArgumentParser,
    *,
    allow_codex_running: bool = False,
    backup_dir: bool = False,
    force: bool = False,
) -> None:
    if allow_codex_running:
        subparser.add_argument(
            "--allow-codex-running",
            action="store_true",
            help="allow operation while Codex appears to be running; use only for inspect",
        )
    if backup_dir:
        subparser.add_argument("--backup-dir", default="~/.codex/session_quarantine")
    if force:
        subparser.add_argument("--force", action="store_true")
