"""Atomic file write helpers using ``os.replace()``.

``os.replace()`` is atomic on POSIX and Windows (Python 3.3+):
https://docs.python.org/3/library/os.html#os.replace

Use these helpers for state / metadata files where a torn write would corrupt
operator-visible records (experiment metadata, calibration index, etc.).
Plain ``Path.write_text`` is fine for log lines or where a partial write
would be detected by downstream parsers.

See DEEP_AUDIT_CC.md D.3 (and Codex D.4).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Atomically write *content* to *path*.

    Writes to a temp file in the same directory (so the rename is atomic
    within a single filesystem), fsyncs, then ``os.replace()``-es into the
    target. On failure the temp file is removed and the original (if any)
    is left intact.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync can fail on some FUSE / network filesystems —
                # the os.replace() below is still atomic, just not durable.
                pass
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Atomic binary write counterpart of :func:`atomic_write_text`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
