"""Audit log retention — delete audit JSON files older than retention_days."""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400


@contextlib.contextmanager
def _owned_directory(path: Path):
    """Hold a no-delete-share handle while deleting from one date directory."""
    if os.name != "nt":
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            yield fd
        finally:
            os.close(fd)
        return
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        str(path),
        0x80000000,
        0x00000001 | 0x00000002,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        error = ctypes.get_last_error()
        raise OSError(error, f"cannot own retention directory: {path}")
    try:
        yield handle
    finally:
        close_handle(handle)


def _is_reparse_point(path: Path) -> bool:
    """Return true for symlinks and Windows junction/reparse objects."""
    try:
        observed = os.lstat(path)
    except OSError:
        return True
    return path.is_symlink() or bool(getattr(observed, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _identity(path: Path) -> tuple[int, int, int, int] | None:
    try:
        observed = os.lstat(path)
    except OSError:
        return None
    return (
        int(getattr(observed, "st_dev", 0)),
        int(getattr(observed, "st_ino", 0)),
        int(getattr(observed, "st_mode", 0)),
        int(getattr(observed, "st_file_attributes", 0)),
    )


async def cleanup_old_audits(audit_dir: Path, retention_days: int) -> int:
    """Delete audit JSON files older than retention_days. Returns count deleted.

    Only removes files whose parent directory name is a YYYY-MM-DD date that
    predates the retention cutoff. Non-date directories and non-JSON files are
    left untouched. Empty date directories are removed after their contents are
    deleted.
    """
    return await asyncio.to_thread(_cleanup_old_audits_sync, Path(audit_dir), retention_days)


def _cleanup_old_audits_sync(audit_dir: Path, retention_days: int) -> int:
    """Synchronous no-follow cleanup body, run outside the event loop."""
    # The configured audit root and each dated child must be real directories.
    # ``Path.is_dir`` follows symlinks, so test ``is_symlink`` first.
    if _is_reparse_point(audit_dir) or not audit_dir.is_dir():
        return 0

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    deleted = 0

    for date_dir in audit_dir.iterdir():
        if _is_reparse_point(date_dir) or not date_dir.is_dir():
            continue
        try:
            dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            continue
        if dir_date >= cutoff:
            continue
        date_identity = _identity(date_dir)
        for f in date_dir.iterdir():
            if f.suffix.casefold() != ".json":
                continue
            # Unlinking a file symlink would not remove its target, but audit
            # retention owns regular JSON evidence files only.
            file_identity = _identity(f)
            if (
                date_identity is None
                or _identity(date_dir) != date_identity
                or file_identity is None
                or _is_reparse_point(f)
                or not f.is_file()
                or _identity(f) != file_identity
            ):
                continue
            try:
                with _owned_directory(date_dir) as directory_fd:
                    if os.name == "posix":
                        os.unlink(f.name, dir_fd=directory_fd)
                    else:
                        f.unlink()
            except OSError:
                continue
            deleted += 1
        try:
            date_dir.rmdir()
        except OSError:
            pass  # leave non-empty dirs (e.g. non-JSON files present)

    if deleted:
        logger.info("retention: deleted %d audit files older than %d days", deleted, retention_days)
    return deleted
