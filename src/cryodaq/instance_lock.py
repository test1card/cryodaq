"""Single-instance lock for GUI processes.

Uses flock (Linux) / msvcrt.locking (Windows) — same kernel-level
mechanism as engine.py. Lock released automatically when process exits.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from cryodaq.paths import get_data_dir

logger = logging.getLogger(__name__)


def try_acquire_lock(lock_name: str) -> int | None:
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
    lock_path = get_data_dir() / lock_name
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        os.close(fd)
        return None

    # Write PID for diagnostics
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def release_lock(fd: int, lock_name: str) -> None:
    """Release lock and remove lock file."""
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        (get_data_dir() / lock_name).unlink(missing_ok=True)
    except OSError:
        pass
