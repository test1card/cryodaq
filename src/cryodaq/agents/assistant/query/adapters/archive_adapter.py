"""ArchiveAdapter — read-only access to the experiment archive for the query agent.

F33: thin wrapper, never writes, never raises — returns ``None`` on any
failure path so the format LLM can render a graceful "no data" reply.

B1: previously called :class:`cryodaq.core.experiment.ExperimentManager`
and :class:`cryodaq.core.alarm_v2.AlarmStateManager` directly (in-process);
now calls the engine's existing read-only ``experiment_archive_list`` /
``experiment_get_archive_item`` / ``alarm_v2_history`` REP commands.
``metadata.json`` for archived (immutable, already-finalized) experiments
is still read directly from disk — it's a static file, not live engine
state, so no ZMQ round-trip is needed for it.

The default time-window is 7 days for both archive listings and alarm-
history summaries, matching the architect's resolution in the F33 spec.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryodaq.agents.assistant.query.schemas import (
    AlarmHistoryResult,
    ArchiveDetailResult,
    ArchiveListResult,
)
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient
from cryodaq.storage._windows_secure_read import (
    SecureRelativeReadError,
    read_secure_relative_bytes,
)

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW_DAYS = 7
_DEFAULT_LIST_LIMIT = 20
_ALARM_HISTORY_FETCH_LIMIT = 1000
_MAX_METADATA_BYTES = 1024 * 1024


def _read_posix_relative_bytes(root: Path, relative: Path) -> bytes:
    """Read a single-link regular file through a no-follow dir-fd walk."""
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        if not hasattr(os, "O_DIRECTORY") or os.open not in os.supports_dir_fd:
            raise OSError("secure relative reads are unavailable")
        directory_flags = os.O_RDONLY | os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        parts = root.parts
        if len(parts) < 2:
            raise OSError("archive root is invalid")
        directory_fd = os.open(parts[0], directory_flags)
        for component in (*parts[1:], *relative.parts[:-1]):
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd

        filename = relative.parts[-1]
        before = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise OSError("metadata must be a single-link regular file")
        if before.st_size > _MAX_METADATA_BYTES:
            raise OSError("metadata exceeds byte limit")

        file_flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            file_flags |= os.O_NOFOLLOW
        file_fd = os.open(filename, file_flags, dir_fd=directory_fd)
        opened = os.fstat(file_fd)
        fingerprint = (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or fingerprint
            != (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
        ):
            raise OSError("metadata changed before reading")

        chunks: list[bytes] = []
        remaining = _MAX_METADATA_BYTES + 1
        while remaining:
            chunk = os.read(file_fd, min(remaining, 65_536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > _MAX_METADATA_BYTES:
            raise OSError("metadata exceeds byte limit")
        after = os.fstat(file_fd)
        if fingerprint != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise OSError("metadata changed while reading")
        return raw
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _read_bounded_metadata(archive_root: Path, metadata_path: str) -> dict[str, Any]:
    """Read one archive-owned metadata file without following filesystem aliases."""
    root = Path(os.path.abspath(os.fspath(archive_root)))
    selected = Path(metadata_path)
    if not selected.is_absolute():
        selected = root / selected
    selected = Path(os.path.abspath(os.fspath(selected)))
    try:
        relative = selected.relative_to(root)
    except ValueError as exc:
        raise OSError("metadata path escapes archive root") from exc
    if not relative.parts or relative.name != "metadata.json":
        raise OSError("metadata path is not an archive metadata file")

    if os.name == "nt":
        try:
            raw = read_secure_relative_bytes(root, relative, max_bytes=_MAX_METADATA_BYTES)
        except SecureRelativeReadError as exc:
            raise OSError("metadata cannot be read safely") from exc
    else:
        raw = _read_posix_relative_bytes(root, relative)
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


class ArchiveAdapter:
    """Read-only adapter exposing the experiment archive + alarm history."""

    def __init__(
        self,
        engine_client: EngineQueryClient,
        *,
        archive_root: Path | None = None,
    ) -> None:
        self._client = engine_client
        self._archive_root = Path(archive_root) if archive_root is not None else None

    # ------------------------------------------------------------------
    # Archive list
    # ------------------------------------------------------------------

    async def list_recent(
        self,
        *,
        days: int = _DEFAULT_WINDOW_DAYS,
        limit: int = _DEFAULT_LIST_LIMIT,
    ) -> ArchiveListResult | None:
        """Return up to ``limit`` archived experiments started within the last
        ``days`` days, newest first."""
        start_date = datetime.now(UTC) - timedelta(days=int(days))
        reply = await self._client.call(
            {
                "cmd": "experiment_archive_list",
                "start_date": start_date.isoformat(),
                "sort_by": "start_time",
                "descending": True,
            }
        )
        if not reply.get("ok"):
            return None
        try:
            entries = reply.get("entries", [])[: int(limit)]
            return ArchiveListResult(
                entries=entries,
                total_count=len(entries),
                filter_summary=f"за последние {int(days)} дней",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ArchiveAdapter.list_recent failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Archive detail
    # ------------------------------------------------------------------

    async def get_detail(self, experiment_id: str) -> ArchiveDetailResult | None:
        """Return the full record for one archived experiment, or ``None``."""
        ident = (experiment_id or "").strip()
        if not ident:
            return None
        reply = await self._client.call({"cmd": "experiment_get_archive_item", "experiment_id": ident})
        if not reply.get("ok"):
            return None
        entry = reply.get("entry")
        if entry is None:
            return None
        try:
            metadata: dict[str, Any] = {}
            meta_path_str = entry.get("metadata_path")
            if meta_path_str and self._archive_root is not None:
                try:
                    metadata = await asyncio.to_thread(
                        _read_bounded_metadata,
                        self._archive_root,
                        str(meta_path_str),
                    )
                except Exception as meta_exc:  # noqa: BLE001
                    logger.debug(
                        "ArchiveAdapter.get_detail: metadata.json read failed for %s: %s",
                        ident,
                        meta_exc,
                    )
            phases_raw = metadata.get("phases", []) if isinstance(metadata, dict) else []
            phases: list[dict] = [dict(p) for p in phases_raw if isinstance(p, dict)]

            start_time = entry.get("start_time")
            end_time = entry.get("end_time")
            duration_h: float | None = None
            if start_time and end_time:
                try:
                    duration_h = (
                        datetime.fromisoformat(end_time) - datetime.fromisoformat(start_time)
                    ).total_seconds() / 3600.0
                except ValueError:
                    duration_h = None

            cooldown_phase = next(
                (p for p in phases if str(p.get("phase", "")).lower() == "cooldown" and p.get("ended_at")),
                None,
            )
            cooldown_metrics: dict | None = None
            if cooldown_phase is not None:
                cooldown_metrics = {
                    "started_at": cooldown_phase.get("started_at"),
                    "ended_at": cooldown_phase.get("ended_at"),
                }

            return ArchiveDetailResult(
                experiment_id=entry.get("experiment_id", ident),
                sample=entry.get("sample", ""),
                operator=entry.get("operator", ""),
                status=entry.get("status", ""),
                started_at=start_time or "",
                ended_at=end_time,
                duration_h=duration_h,
                phases=phases,
                cooldown_metrics=cooldown_metrics,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ArchiveAdapter.get_detail failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Alarm history
    # ------------------------------------------------------------------

    async def alarm_history_summary(
        self,
        *,
        days: int = _DEFAULT_WINDOW_DAYS,
    ) -> AlarmHistoryResult | None:
        """Aggregate triggered/cleared transitions from the alarm-v2 history."""
        cutoff = (datetime.now(UTC) - timedelta(days=int(days))).timestamp()
        reply = await self._client.call(
            {
                "cmd": "alarm_v2_history",
                "start_ts": cutoff,
                "limit": _ALARM_HISTORY_FETCH_LIMIT,
            }
        )
        if not reply.get("ok"):
            return None
        try:
            history = reply.get("history", [])
            triggered = 0
            cleared = 0
            by_alarm_id: dict[str, int] = {}

            for entry in history:
                if not isinstance(entry, dict):
                    continue
                transition = str(entry.get("transition", "")).upper()
                alarm_id = str(entry.get("alarm_id", "unknown"))
                if transition == "TRIGGERED":
                    triggered += 1
                    by_alarm_id[alarm_id] = by_alarm_id.get(alarm_id, 0) + 1
                elif transition == "CLEARED":
                    cleared += 1

            return AlarmHistoryResult(
                window_description=f"за последние {int(days)} дней",
                triggered_count=triggered,
                cleared_count=cleared,
                by_alarm_id=by_alarm_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ArchiveAdapter.alarm_history_summary failed: %s", exc)
            return None
