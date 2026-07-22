"""Single-instance lock for GUI processes.

Uses flock (Linux) / msvcrt.locking (Windows) — same kernel-level
mechanism as engine.py. Lock released automatically when process exits.
"""

from __future__ import annotations

import logging
import os
import stat
import sys
from pathlib import Path

from cryodaq.paths import get_data_dir

logger = logging.getLogger(__name__)


def _lock_path(lock_name: str, lock_dir: Path | None) -> Path:
    relative = Path(lock_name)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("lock_name must be a relative path without '..'")
    raw_root = Path(lock_dir if lock_dir is not None else get_data_dir())
    raw_root.mkdir(parents=True, exist_ok=True)
    root_info = raw_root.lstat()
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise ValueError("lock directory must be a real directory")
    root = raw_root.resolve(strict=True)
    parent = root
    for part in relative.parts[:-1]:
        parent /= part
        if not os.path.lexists(parent):
            try:
                parent.mkdir(mode=0o700)
            except FileExistsError:
                # Another contender may create the shared lock parent after
                # our existence check.  Validate what won the race below;
                # files and symlinks remain forbidden.
                pass
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("lock parent must be a real directory")
    path = parent / relative.name
    resolved_parent = parent.resolve(strict=True)
    if resolved_parent != root and root not in resolved_parent.parents:
        raise ValueError("lock_name escapes the lock directory")
    return path


def try_acquire_lock(lock_name: str, *, lock_dir: Path | None = None) -> int | None:
    """Try to acquire an exclusive process lock.

    Parameters
    ----------
    lock_name:
        Lock file name, e.g. ".launcher.lock" or ".gui.lock".
        Stored in get_data_dir().

    Returns
    -------
    File descriptor on success, None if lock is held by another process.
    """
    lock_path = _lock_path(lock_name, lock_dir)
    before: os.stat_result | None = None
    try:
        if os.path.lexists(lock_path):
            before = lock_path.lstat()
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                return None
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(lock_path), flags, 0o600)
    except OSError:
        return None
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            os.close(fd)
            return None
        if before is not None and not os.path.samestat(before, opened):
            os.close(fd)
            return None
        try:
            path_info = lock_path.lstat()
        except OSError:
            os.close(fd)
            return None
        if stat.S_ISLNK(path_info.st_mode) or not os.path.samestat(opened, path_info):
            os.close(fd)
            return None
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None

    try:
        after_lock = os.fstat(fd)
        path_after_lock = lock_path.lstat()
    except OSError:
        os.close(fd)
        return None
    if (
        not stat.S_ISREG(after_lock.st_mode)
        or after_lock.st_nlink != 1
        or not os.path.samestat(opened, after_lock)
        or stat.S_ISLNK(path_after_lock.st_mode)
        or not os.path.samestat(opened, path_after_lock)
    ):
        os.close(fd)
        return None

    # Write PID for diagnostics
    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"{os.getpid()}\n".encode())
        os.fsync(fd)
    except OSError:
        os.close(fd)
        return None
    return fd


def release_lock(
    fd: int,
    lock_name: str,
    *,
    unlink: bool = True,
    lock_dir: Path | None = None,
) -> None:
    """Release a lock, optionally retaining its stable lock-file inode.

    Existing launcher/GUI callers retain the historical unlinking default.
    High-contention report locks pass ``unlink=False``: unlinking after close
    creates a POSIX race where another contender can lock the old inode while
    a third contender creates and locks a new one at the same path.
    """
    if unlink:
        try:
            lock_path = _lock_path(lock_name, lock_dir)
            opened = os.fstat(fd)
            path_info = lock_path.lstat()
            if (
                stat.S_ISREG(opened.st_mode)
                and opened.st_nlink == 1
                and not stat.S_ISLNK(path_info.st_mode)
                and os.path.samestat(opened, path_info)
            ):
                lock_path.unlink()
        except OSError:
            pass
    try:
        os.close(fd)
    except OSError:
        pass


def release_lock_exact(
    fd: int,
    lock_name: str,
    *,
    lock_dir: Path | None = None,
) -> None:
    """Release a process lock without an unlink race or swallowed close.

    Long-lived single-instance owners use this terminal form after their event
    loop has returned. Keeping the stable inode avoids the POSIX split-lock
    race created by unlinking before the incumbent descriptor is closed.
    """

    lock_path = _lock_path(lock_name, lock_dir)
    opened = os.fstat(fd)
    try:
        path_info = lock_path.lstat()
    except OSError:
        path_info = None
    if path_info is not None and (
        stat.S_ISLNK(path_info.st_mode)
        or not stat.S_ISREG(path_info.st_mode)
        or not os.path.samestat(opened, path_info)
    ):
        logger.warning("Lock path identity changed before exact release: %s", lock_path)
    os.close(fd)
