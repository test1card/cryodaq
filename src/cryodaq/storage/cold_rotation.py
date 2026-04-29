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
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

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

_CHUNK_SIZE = 100_000


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

        today = (now or datetime.now(UTC)).date()
        candidates = await asyncio.to_thread(self._find_candidates, today)

        results: list[RotationResult] = []
        for db_path in candidates:
            result = await self._rotate_file(db_path, today=today)
            if result is not None:
                results.append(result)

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
            logger.exception(
                "Failed to write Parquet for %s — leaving SQLite intact", db_path.name
            )
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

        # Step 4: Update index
        size_archive = archive_path.stat().st_size
        checksum = self._md5_hex(archive_path)
        rotated_at = datetime.now(UTC)
        self._update_index(
            db_path=db_path,
            archive_rel=archive_rel,
            row_count=expected_rows,
            size_original=size_original,
            size_archive=size_archive,
            checksum=checksum,
            rotated_at=rotated_at,
        )

        # Step 5: Delete SQLite + sidecars
        for suffix in ("", "-wal", "-shm"):
            sidecar = db_path.parent / (db_path.name + suffix)
            sidecar.unlink(missing_ok=True)

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

    def _read_all_rows(
        self, db_path: Path
    ) -> list[tuple[float, str, str, float, str, str]]:
        """Return all rows from readings table as list of tuples."""
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT timestamp, instrument_id, channel, value, unit, status "
                "FROM readings ORDER BY timestamp"
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

    # ------------------------------------------------------------------
    # Parquet write
    # ------------------------------------------------------------------

    def _write_parquet(
        self, archive_path: Path, rows: list[tuple[float, str, str, float, str, str]]
    ) -> None:
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

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

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
            logger.warning("Failed to parse index.json — treating as empty")
            return {"files": []}

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
    ) -> None:
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        idx = self._read_index()
        idx["files"].append(
            {
                "original_name": db_path.name,
                "archive_path": archive_rel,
                "rotated_at": rotated_at.isoformat(),
                "row_count": row_count,
                "size_bytes_original": size_original,
                "size_bytes_archive": size_archive,
                "checksum_md5": checksum,
            }
        )
        self._index_path().write_text(
            json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8"
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
