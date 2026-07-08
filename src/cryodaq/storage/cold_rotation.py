"""Cold-storage rotation: SQLite daily files → Parquet archive after age_days threshold.

F17 implementation. Rotates old daily SQLite files (data_YYYY-MM-DD.db) to
Parquet with Zstd compression.  Today's active write file is never rotated.
All blocking I/O is offloaded via asyncio.to_thread() (same pattern as
SQLiteWriter).

Archive layout: <archive_dir>/year=YYYY/month=MM/<stem>.parquet
Archive index:  <archive_dir>/index.json
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from cryodaq.core.atomic_write import atomic_write_text
from cryodaq.storage._sqlite import sqlite3

logger = logging.getLogger(__name__)

# Parquet schema for cold rotation: same columns as parquet_archive.py minus
# experiment_id (cold rotation has no experiment context per F17 spec).
_COLD_SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("us", tz="UTC")),
        ("instrument_id", pa.string()),
        ("channel", pa.string()),
        ("value", pa.float64()),
        ("unit", pa.string()),
        ("status", pa.string()),
    ]
)

# Parquet schema for the operator_log audit trail (CR-3). The daily SQLite
# file also holds operator_log; rotation must preserve it or the audit trail is
# lost forever when the DB is unlinked. Timestamp kept as raw epoch float for a
# lossless audit record.
_OPERATOR_LOG_SCHEMA = pa.schema(
    [
        ("timestamp", pa.float64()),
        ("experiment_id", pa.string()),
        ("author", pa.string()),
        ("source", pa.string()),
        ("message", pa.string()),
        ("tags", pa.string()),
    ]
)

_CHUNK_SIZE = 100_000


def seconds_until_next(schedule_time: str, now: datetime) -> float:
    """Seconds from *now* until the next daily ``HH:MM`` occurrence.

    Used by the engine to run rotation once per day at the configured quiet
    hour. If today's slot has already passed, returns the delay to tomorrow's.
    """
    hour_str, minute_str = schedule_time.split(":")
    target = now.replace(hour=int(hour_str), minute=int(minute_str), second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def normalize_schedule_time(raw: str) -> str:
    """Return *raw* if it is a valid ``HH:MM``, else fall back to ``"03:00"``.

    The engine's scheduler evaluates ``seconds_until_next`` outside its per-pass
    ``try``, so a malformed ``schedule_time`` would raise once and kill the
    rotation task silently at 3am. Validate loudly here at build time and fall
    back to a sane hour so rotation still runs — the operator sees the ERROR.
    """
    try:
        seconds_until_next(raw, datetime.now(UTC))
        return raw
    except (ValueError, TypeError):
        logger.error(
            "ColdRotation: schedule_time %r некорректен (ожидается HH:MM) — откат на 03:00",
            raw,
        )
        return "03:00"


def build_cold_rotation_service(
    cold_cfg: dict,
    *,
    data_dir: Path,
    project_root: Path,
) -> ColdRotationService | None:
    """Construct a ColdRotationService from the ``cold_rotation`` config block.

    Fail-closed: returns ``None`` unless ``enabled`` is the strict boolean
    ``True``. Any other value (missing, ``"true"`` string, ``1``, ``False``)
    leaves rotation off — a config typo must never silently arm file deletion.

    ``archive_dir`` from config is resolved relative to *project_root* (matching
    ``config/housekeeping.yaml``'s ``data/archive``); an absolute path is used
    verbatim.
    """
    if cold_cfg.get("enabled") is not True:
        return None
    archive_cfg = str(cold_cfg.get("archive_dir", "data/archive"))
    archive_dir = Path(archive_cfg)
    if not archive_dir.is_absolute():
        archive_dir = project_root / archive_dir
    return ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=int(cold_cfg.get("age_days", 30)),
        enabled=True,
        zstd_level=int(cold_cfg.get("zstd_compression_level", 3)),
    )


@dataclass
class RotationResult:
    """Outcome of a single successful SQLite → Parquet rotation."""

    db_path: Path
    archive_path: Path
    rows: int
    size_original: int
    size_archive: int
    rotated_at: datetime


class ColdRotationService:
    """Daemon that rotates aged daily SQLite files to Parquet cold storage.

    Parameters
    ----------
    data_dir:
        Directory containing daily ``data_YYYY-MM-DD.db`` files.
    archive_dir:
        Destination for Parquet files and ``index.json``.
    age_days:
        Files older than this many days (compared to today) are eligible.
    enabled:
        When False, ``run_once()`` is a no-op and returns [].
    zstd_level:
        Zstandard compression level (1–22, default 3).
    """

    def __init__(
        self,
        data_dir: Path,
        archive_dir: Path,
        age_days: int = 30,
        enabled: bool = True,
        zstd_level: int = 3,
    ) -> None:
        self._data_dir = data_dir
        self._archive_dir = archive_dir
        self._age_days = age_days
        self._enabled = enabled
        self._zstd_level = zstd_level
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_once(self, *, now: datetime | None = None) -> list[RotationResult]:
        """Single housekeeping pass: find old files, rotate each one.

        Parameters
        ----------
        now:
            Override "today" for testing purposes.

        Returns
        -------
        list[RotationResult]
            Successfully rotated files. Failed files are logged and skipped.
        """
        if not self._enabled:
            return []

        async with self._lock:
            today = (now or datetime.now(UTC)).date()
            candidates = await asyncio.to_thread(self._find_candidates, today)

            results: list[RotationResult] = []
            for db_path in candidates:
                result = await self._rotate_file(db_path, today=today)
                if result is not None:
                    results.append(result)

            # Retry deletion of any hot DB archived+indexed on a prior pass whose
            # unlink failed (e.g. a transient Windows file lock). Deletion-only:
            # never re-copies, and _find_candidates already skips indexed days so
            # they would otherwise linger forever (F5).
            await asyncio.to_thread(self._sweep_stranded)

            return results

    async def start(self) -> None:
        """Start the daily rotation daemon task."""
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="cold_rotation_service")

    async def stop(self) -> None:
        """Stop the daemon gracefully."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    # ------------------------------------------------------------------
    # Daemon loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Run once per day; sleep 24 h between passes."""
        try:
            while self._running:
                await self.run_once()
                await asyncio.sleep(86_400)
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------
    # Core rotation logic
    # ------------------------------------------------------------------

    def _is_active_db(self, db_path: Path, today: date) -> bool:
        """Return True if *db_path* is today's write-active file."""
        expected_name = f"data_{today.isoformat()}.db"
        return db_path.name == expected_name

    def _find_candidates(self, today: date) -> list[Path]:
        """Return sorted list of DB files older than age_days that are not
        today's active file and have not already been rotated."""
        cutoff = today - timedelta(days=self._age_days)
        # Load already-rotated names from index so we don't re-process them
        rotated = self._load_rotated_names()

        candidates: list[Path] = []
        for db_path in sorted(self._data_dir.glob("data_????-??-??.db")):
            if self._is_active_db(db_path, today):
                continue
            if db_path.name in rotated:
                continue
            try:
                day = date.fromisoformat(db_path.stem.removeprefix("data_"))
            except ValueError:
                logger.warning("Unexpected DB filename format: %s — skipping", db_path.name)
                continue
            if day < cutoff:
                candidates.append(db_path)
        return candidates

    async def _rotate_file(self, db_path: Path, today: date) -> RotationResult | None:
        """Rotate one SQLite file to Parquet.

        Sequence:
        1. Read all rows from SQLite.
        2. Write Parquet with Zstd compression.
        3. Verify row count matches.
        4. Update index.json.
        5. Delete SQLite + WAL + SHM sidecars.

        Returns None on any failure (partial Parquet cleaned up).
        """
        return await asyncio.to_thread(self._rotate_file_sync, db_path, today)

    def _rotate_file_sync(self, db_path: Path, today: date) -> RotationResult | None:
        """Synchronous worker called via asyncio.to_thread."""
        # Derive archive path from DB filename date
        try:
            day = date.fromisoformat(db_path.stem.removeprefix("data_"))
        except ValueError:
            logger.error("Cannot parse date from DB filename: %s", db_path.name)
            return None

        archive_rel = f"year={day.year}/month={day.month:02d}/{db_path.stem}.parquet"
        archive_path = self._archive_dir / archive_rel

        size_original = db_path.stat().st_size

        # Step 0 (CR-3 follow-up): source_data has no cold-storage export yet.
        # If this day carries source_data rows, do NOT rotate at all. Rotating
        # would either destroy them (Step 5 delete) or leave the file kept but
        # already index-marked as rotated — excluding it from future candidates
        # forever and double-counting its readings for any reader that unions
        # the live DB with the cold Parquet. Skip cleanly (nothing written,
        # nothing indexed, file stays a candidate); revisit when source_data
        # gains a cold-export path.
        if self._table_has_rows(db_path, "source_data"):
            logger.warning(
                "source_data in %s has rows and no cold export exists — "
                "skipping rotation entirely (SQLite kept, not indexed)",
                db_path.name,
            )
            return None

        # Step 1: Read all rows from SQLite
        try:
            rows = self._read_all_rows(db_path)
        except Exception:
            logger.exception("Failed to read SQLite %s — skipping rotation", db_path.name)
            return None

        expected_rows = len(rows)

        # Step 2: Write Parquet (any exception → clean up partial file)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._write_parquet(archive_path, rows)
        except Exception:
            logger.exception("Failed to write Parquet for %s — leaving SQLite intact", db_path.name)
            # Clean up any partial Parquet file
            archive_path.unlink(missing_ok=True)
            return None

        # Step 3: Verify row count
        try:
            actual_rows = pq.read_metadata(str(archive_path)).num_rows
        except Exception:
            logger.exception(
                "Cannot verify Parquet row count for %s — leaving SQLite intact",
                db_path.name,
            )
            archive_path.unlink(missing_ok=True)
            return None

        if actual_rows != expected_rows:
            logger.error(
                "Row count mismatch for %s: expected %d, got %d — leaving SQLite intact",
                db_path.name,
                expected_rows,
                actual_rows,
            )
            archive_path.unlink(missing_ok=True)
            return None

        # Step 3.5: Preserve operator_log audit trail (CR-3). The daily DB also
        # holds operator_log; without this the whole audit trail is destroyed
        # when the SQLite file is unlinked in Step 5.
        operator_log_rel: str | None = None
        operator_log_rows_count = 0
        try:
            operator_log_rows = self._read_operator_log_rows(db_path)
        except Exception:
            logger.exception(
                "Failed to read operator_log from %s — leaving SQLite intact, cleaning up Parquet",
                db_path.name,
            )
            archive_path.unlink(missing_ok=True)
            return None

        if operator_log_rows:
            operator_log_rel = f"year={day.year}/month={day.month:02d}/{db_path.stem}.operator_log.parquet"
            operator_log_path = self._archive_dir / operator_log_rel
            operator_log_rows_count = len(operator_log_rows)
            try:
                self._write_operator_log_parquet(operator_log_path, operator_log_rows)
                actual_ol = pq.read_metadata(str(operator_log_path)).num_rows
                if actual_ol != operator_log_rows_count:
                    raise RuntimeError(
                        f"operator_log row count mismatch: expected {operator_log_rows_count}, got {actual_ol}"
                    )
            except Exception:
                logger.exception(
                    "Failed to preserve operator_log for %s — leaving SQLite intact, cleaning up Parquet",
                    db_path.name,
                )
                operator_log_path.unlink(missing_ok=True)
                archive_path.unlink(missing_ok=True)
                return None

        # Step 4: Update index. Record the source .db's own MD5 alongside the
        # Parquet checksum: the sweep uses it to prove a stranded hot DB is
        # byte-identical to what was archived before it dares delete it. Nothing
        # touches db_path between here and the Step-5 unlink, so this hash is
        # exactly what would be deleted.
        size_archive = archive_path.stat().st_size
        checksum = self._md5_hex(archive_path)
        source_md5 = self._md5_hex(db_path)
        rotated_at = datetime.now(UTC)
        try:
            self._update_index(
                db_path=db_path,
                archive_rel=archive_rel,
                row_count=expected_rows,
                size_original=size_original,
                size_archive=size_archive,
                checksum=checksum,
                source_md5=source_md5,
                rotated_at=rotated_at,
                operator_log_rel=operator_log_rel,
                operator_log_rows=operator_log_rows_count,
            )
        except Exception:
            logger.exception(
                "Failed to update index for %s — leaving SQLite intact, cleaning up Parquet",
                db_path.name,
            )
            archive_path.unlink(missing_ok=True)
            if operator_log_rel is not None:
                (self._archive_dir / operator_log_rel).unlink(missing_ok=True)
            return None

        # Step 5: Delete SQLite + sidecars. Safe now: readings and operator_log
        # are preserved in Parquet, and source_data was verified empty at entry
        # (Step 0), so no table with rows is destroyed.
        #
        # A failed unlink (e.g. a Windows file lock) must NOT abort the pass or
        # re-copy: the day is already indexed (Step 4), so _sweep_stranded on
        # the next pass retries the deletion only. Until then the lingering hot
        # .db and its Parquet both exist for the day — ArchiveReader.query_rows
        # unions and dedups them (F4), so no row is hidden or double-counted.
        for suffix in ("", "-wal", "-shm"):
            sidecar = db_path.parent / (db_path.name + suffix)
            try:
                sidecar.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    "Could not delete %s after archiving (kept, retry next pass): %s",
                    sidecar.name,
                    exc,
                )

        logger.info(
            "Rotated %s → %s (%d rows, %.1f MB → %.1f MB)",
            db_path.name,
            archive_rel,
            expected_rows,
            size_original / 1e6,
            size_archive / 1e6,
        )

        return RotationResult(
            db_path=db_path,
            archive_path=archive_path,
            rows=expected_rows,
            size_original=size_original,
            size_archive=size_archive,
            rotated_at=rotated_at,
        )

    # ------------------------------------------------------------------
    # SQLite read
    # ------------------------------------------------------------------

    def _read_all_rows(self, db_path: Path) -> list[tuple[float, str, str, float, str, str]]:
        """Return all rows from readings table as list of tuples."""
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT timestamp, instrument_id, channel, value, unit, status FROM readings ORDER BY timestamp"
            )
            return [
                (
                    float(row["timestamp"]),
                    str(row["instrument_id"]),
                    str(row["channel"]),
                    float(row["value"]),
                    str(row["unit"]),
                    str(row["status"]),
                )
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None

    def _read_operator_log_rows(self, db_path: Path) -> list[tuple[float, str | None, str, str, str, str]]:
        """Return all operator_log rows as tuples (empty if table absent)."""
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            if not self._table_exists(conn, "operator_log"):
                return []
            cursor = conn.execute(
                "SELECT timestamp, experiment_id, author, source, message, tags FROM operator_log ORDER BY timestamp"
            )
            return [
                (
                    float(row["timestamp"]),
                    None if row["experiment_id"] is None else str(row["experiment_id"]),
                    str(row["author"]),
                    str(row["source"]),
                    str(row["message"]),
                    str(row["tags"]),
                )
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def _table_has_rows(self, db_path: Path, table: str) -> bool:
        """Return True if *table* exists in *db_path* and holds at least one row."""
        conn = sqlite3.connect(str(db_path), timeout=10)
        try:
            if not self._table_exists(conn, table):
                return False
            row = conn.execute(f"SELECT EXISTS(SELECT 1 FROM {table})").fetchone()
            return bool(row[0])
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Parquet write
    # ------------------------------------------------------------------

    def _write_parquet(self, archive_path: Path, rows: list[tuple[float, str, str, float, str, str]]) -> None:
        """Stream rows to Parquet in chunks with Zstd compression."""
        writer = pq.ParquetWriter(
            str(archive_path),
            _COLD_SCHEMA,
            compression="zstd",
            compression_level=self._zstd_level,
        )
        try:
            offset = 0
            while offset < len(rows):
                chunk = rows[offset : offset + _CHUNK_SIZE]
                offset += _CHUNK_SIZE

                timestamps = []
                instruments = []
                channels = []
                values = []
                units = []
                statuses = []

                for ts_epoch, inst, ch, val, unit, status in chunk:
                    timestamps.append(datetime.fromtimestamp(ts_epoch, tz=UTC))
                    instruments.append(inst)
                    channels.append(ch)
                    values.append(val)
                    units.append(unit)
                    statuses.append(status)

                batch = pa.table(
                    {
                        "timestamp": pa.array(timestamps, type=pa.timestamp("us", tz="UTC")),
                        "instrument_id": pa.array(instruments),
                        "channel": pa.array(channels),
                        "value": pa.array(values, type=pa.float64()),
                        "unit": pa.array(units),
                        "status": pa.array(statuses),
                    },
                    schema=_COLD_SCHEMA,
                )
                writer.write_table(batch)
        finally:
            writer.close()

    def _write_operator_log_parquet(
        self,
        archive_path: Path,
        rows: list[tuple[float, str | None, str, str, str, str]],
    ) -> None:
        """Write operator_log rows to a companion Parquet file (Zstd)."""
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        timestamps: list[float] = []
        experiment_ids: list[str | None] = []
        authors: list[str] = []
        sources: list[str] = []
        messages: list[str] = []
        tags: list[str] = []
        for ts_epoch, exp_id, author, source, message, tag in rows:
            timestamps.append(ts_epoch)
            experiment_ids.append(exp_id)
            authors.append(author)
            sources.append(source)
            messages.append(message)
            tags.append(tag)

        table = pa.table(
            {
                "timestamp": pa.array(timestamps, type=pa.float64()),
                "experiment_id": pa.array(experiment_ids, type=pa.string()),
                "author": pa.array(authors, type=pa.string()),
                "source": pa.array(sources, type=pa.string()),
                "message": pa.array(messages, type=pa.string()),
                "tags": pa.array(tags, type=pa.string()),
            },
            schema=_OPERATOR_LOG_SCHEMA,
        )
        pq.write_table(
            table,
            str(archive_path),
            compression="zstd",
            compression_level=self._zstd_level,
        )

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def _sweep_stranded(self) -> None:
        """Retry deleting hot DBs already archived+indexed but still on disk.

        Rotation writes index.json BEFORE unlinking the hot SQLite (the correct
        fail-safe: never delete data before the archive is recorded). If that
        unlink fails — e.g. a Windows file lock — the day stays indexed and
        _find_candidates skips it forever, so the hot .db would linger undeleted.
        Sweep those strays each pass and retry the deletion only, after verifying
        both the archive Parquet and its index entry exist. Until a retry
        succeeds ArchiveReader.query_rows unions the lingering .db with its
        Parquet (F4), so no row is hidden or double-counted. One locked file
        never aborts the sweep or the rotation pass.
        """
        try:
            idx = self._read_index()
        except RuntimeError:
            return  # corrupt index already logged in _read_index; do not touch files
        for entry in idx.get("files", []):
            name = entry.get("original_name")
            archive_rel = entry.get("archive_path")
            if not name or not archive_rel:
                continue
            db_path = self._data_dir / name
            if not db_path.exists():
                continue
            # Never delete the hot copy unless its Parquet is actually present.
            if not (self._archive_dir / archive_rel).exists():
                logger.warning(
                    "Stranded hot DB %s is indexed but Parquet %s is missing — "
                    "NOT deleting (archive incomplete)",
                    name,
                    archive_rel,
                )
                continue
            # Hash-gated delete: reclaim ONLY the genuine stranded original.
            # Parquet+index existence proves an archive exists — NOT that this
            # hot DB's contents are contained in it. A restored/backdated day may
            # carry new operator rows absent from the Parquet; deleting it would
            # silently destroy them. Delete only when the DB is byte-identical to
            # what was archived and has no uncommitted WAL/SHM sidecar.
            day = name.removeprefix("data_").removesuffix(".db")
            source_md5 = entry.get("source_md5")
            if source_md5 is None:
                logger.warning(
                    "Stranded hot DB %s (day %s): legacy index entry has no "
                    "source_md5 — KEEPING, cannot prove byte-identity to the "
                    "archive. The overlap union keeps both sources visible; "
                    "operator decides.",
                    name,
                    day,
                )
                continue
            try:
                current_md5 = self._md5_hex(db_path)
            except OSError as exc:
                logger.warning(
                    "Stranded hot DB %s (day %s): cannot hash — KEEPING: %s",
                    name,
                    day,
                    exc,
                )
                continue
            if current_md5 != source_md5:
                logger.warning(
                    "Stranded hot DB %s (day %s): current contents differ from "
                    "what was archived (restored/backdated/modified) — KEEPING to "
                    "avoid data loss. The overlap union keeps both sources "
                    "visible; operator decides.",
                    name,
                    day,
                )
                continue
            sidecar_blocks = False
            for suffix in ("-wal", "-shm"):
                side = db_path.parent / (db_path.name + suffix)
                try:
                    if side.exists() and side.stat().st_size > 0:
                        sidecar_blocks = True
                        break
                except OSError:
                    sidecar_blocks = True
                    break
            if sidecar_blocks:
                logger.warning(
                    "Stranded hot DB %s (day %s): a non-empty WAL/SHM sidecar is "
                    "present — KEEPING, uncommitted data may not be in the "
                    "archive. The overlap union keeps both sources visible; "
                    "operator decides.",
                    name,
                    day,
                )
                continue
            for suffix in ("", "-wal", "-shm"):
                sidecar = db_path.parent / (db_path.name + suffix)
                try:
                    sidecar.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning(
                        "Retry deleting stranded %s failed (retry next pass): %s",
                        sidecar.name,
                        exc,
                    )

    def _index_path(self) -> Path:
        return self._archive_dir / "index.json"

    def _load_rotated_names(self) -> set[str]:
        """Return set of original_name values already in index."""
        idx = self._read_index()
        return {entry["original_name"] for entry in idx.get("files", [])}

    def _read_index(self) -> dict:
        path = self._index_path()
        if not path.exists():
            return {"files": []}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.error(
                "Archive index.json at %s is corrupt — aborting rotation to protect archive "
                "records. Inspect and repair or delete the file manually.",
                path,
            )
            raise RuntimeError(f"Archive index.json corrupt: {path}")

    def _update_index(
        self,
        *,
        db_path: Path,
        archive_rel: str,
        row_count: int,
        size_original: int,
        size_archive: int,
        checksum: str,
        rotated_at: datetime,
        source_md5: str | None = None,
        operator_log_rel: str | None = None,
        operator_log_rows: int = 0,
    ) -> None:
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        idx = self._read_index()
        entry = {
            "original_name": db_path.name,
            "archive_path": archive_rel,
            "rotated_at": rotated_at.isoformat(),
            "row_count": row_count,
            "size_bytes_original": size_original,
            "size_bytes_archive": size_archive,
            "checksum_md5": checksum,
        }
        if source_md5 is not None:
            entry["source_md5"] = source_md5
        if operator_log_rel is not None:
            entry["operator_log_path"] = operator_log_rel
            entry["operator_log_rows"] = operator_log_rows
        idx["files"].append(entry)
        # Atomic write (temp + os.replace): a crash mid-write must never leave a
        # truncated index.json that bricks both rotation and ArchiveReader reads.
        atomic_write_text(
            self._index_path(),
            json.dumps(idx, indent=2, ensure_ascii=False),
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _md5_hex(path: Path) -> str:
        """Return hex-encoded MD5 digest of file contents."""
        h = hashlib.md5()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(65_536), b""):
                h.update(block)
        return h.hexdigest()
