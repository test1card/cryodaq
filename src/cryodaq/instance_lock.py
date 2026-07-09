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


def _lock_path(lock_name: str, lock_dir: Path | None) -> Path:
    relative = Path(lock_name)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("lock_name must be a relative path without '..'")
    root = (lock_dir if lock_dir is not None else get_data_dir()).resolve()
    path = root.joinpath(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = path.parent.resolve()
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
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None

    # Write PID for diagnostics
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{os.getpid()}\n".encode())
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
    try:
        os.close(fd)
    except OSError:
        pass
    if unlink:
        try:
            _lock_path(lock_name, lock_dir).unlink(missing_ok=True)
        except OSError:
            pass
