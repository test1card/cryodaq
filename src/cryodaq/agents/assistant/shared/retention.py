"""Audit log retention — delete audit JSON files older than retention_days."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


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
    if audit_dir.is_symlink() or not audit_dir.is_dir():
        return 0

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    deleted = 0

    for date_dir in audit_dir.iterdir():
        if date_dir.is_symlink() or not date_dir.is_dir():
            continue
        try:
            dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            continue
        if dir_date >= cutoff:
            continue
        for f in date_dir.glob("*.json"):
            # Unlinking a file symlink would not remove its target, but audit
            # retention owns regular JSON evidence files only.
            if f.is_symlink() or not f.is_file():
                continue
            f.unlink()
            deleted += 1
        try:
            date_dir.rmdir()
        except OSError:
            pass  # leave non-empty dirs (e.g. non-JSON files present)

    if deleted:
        logger.info("retention: deleted %d audit files older than %d days", deleted, retention_days)
    return deleted
