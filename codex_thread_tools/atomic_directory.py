from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import time
from typing import Callable, IO, Iterator
from uuid import uuid4

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class _RestoreFailedError(RuntimeError):
    """Raised when restoring a backup after install failure fails."""


@contextmanager
def staged_directory(
    target: Path,
    *,
    replace: bool,
    before_stage: Callable[[], None] | None = None,
    before_publish: Callable[[], None] | None = None,
) -> Iterator[Path]:
    """Yield a sibling staging directory and atomically install it on success."""
    target = target.expanduser()
    if target.is_symlink():
        raise ValueError(f"archive target is a symlink: {target}")

    target_parent = target.parent
    if before_stage is not None:
        before_stage()
    reservation = _reservation_path(target)
    reservation_handle = _acquire_reservation(reservation)
    try:
        if target.exists() and not replace:
            raise ValueError(
                f"archive already exists: {target} (use --force to overwrite)"
            )

        token = uuid4().hex
        staging = _sibling_path(target_parent, "staging", token)
        backup = _sibling_path(target_parent, "backup", token)

        staging.mkdir(parents=True)
        keep_backup = False

        try:
            yield staging

            if before_publish is not None:
                before_publish()

            if not replace:
                if target.exists():
                    raise ValueError(
                        f"archive already exists: {target} (use --force to overwrite)"
                    )
                staging.rename(target)
                return

            if target.exists():
                target.rename(backup)
                try:
                    staging.rename(target)
                except BaseException as exc:
                    keep_backup = True
                    try:
                        backup.rename(target)
                    except BaseException as restore_exc:
                        raise _RestoreFailedError(
                            "failed to restore backup after staging install failure: "
                            f"{backup}"
                        ) from restore_exc
                    keep_backup = False
                    raise exc
                try:
                    _remove_path(backup)
                except OSError:
                    # The replacement is already live; retain the old archive for recovery.
                    pass
            else:
                staging.rename(target)
        except BaseException:
            _remove_path(staging)
            if not keep_backup and backup.exists():
                _remove_path(backup)
            raise
    finally:
        _release_reservation(reservation_handle)


def _reservation_path(target: Path) -> Path:
    digest = hashlib.sha256(str(target).encode("utf-8")).hexdigest()[:16]
    return target.parent / f".codex-thread-tools-reservation-{digest}"


def _sibling_path(parent: Path, kind: str, token: str) -> Path:
    return parent / f".codex-thread-tools-{kind}-{token}"


def _acquire_reservation(path: Path) -> IO[str]:
    os.makedirs(path.parent, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    handle = os.fdopen(fd, "r+", encoding="ascii")
    try:
        if os.fstat(fd).st_size == 0:
            handle.write("\0")
            handle.flush()
        _lock_reservation_file(handle, path)
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\ncreated_ns={time.time_ns()}\n")
        handle.flush()
        os.fsync(handle.fileno())
        return handle
    except BaseException:
        handle.close()
        raise


def _lock_reservation_file(handle: IO[str], path: Path) -> None:
    try:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise ValueError(
            f"archive target is reserved by another process: {path}"
        ) from exc


def _release_reservation(handle: IO[str]) -> None:
    try:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


@contextmanager
def target_reservation(target: Path) -> Iterator[None]:
    reservation = _reservation_path(target.expanduser())
    reservation_handle = _acquire_reservation(reservation)
    try:
        yield
    finally:
        _release_reservation(reservation_handle)


def _remove_path(path: Path) -> None:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
            return
        if path.is_dir():
            for child in path.iterdir():
                _remove_path(child)
            path.rmdir()
    except FileNotFoundError:
        return
