"""Parquet export/read for experiment data archive.

Phase 2e stage 1: export_experiment_readings_to_parquet() streams rows from
daily SQLite files into a single Parquet file during experiment finalization.

pyarrow is OPTIONAL — functions degrade gracefully if not installed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.archive_reader import ArchiveReader
from cryodaq.storage.sentinel import decode

logger = logging.getLogger(__name__)

_DEFAULT_CHUNK_SIZE = 100_000


@dataclass
class ParquetExportResult:
    output_path: Path
    rows_written: int
    file_size_bytes: int
    duration_s: float
    skipped_days: list[str] = field(default_factory=list)
    # Days whose rows came from cold Parquet (F17 rotated) instead of a daily
    # SQLite file. Cold rows carry no experiment_id, so their exported
    # experiment_id column is null — surfaced here so the caller can say so.
    archived_days: list[str] = field(default_factory=list)


def export_experiment_readings_to_parquet(
    experiment_id: str,
    start_time: datetime,
    end_time: datetime,
    sqlite_root: Path,
    output_path: Path,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> ParquetExportResult:
    """Export readings within [start_time, end_time] from daily SQLite files
    into a single Parquet file at output_path.

    Streams rows in chunks via pyarrow.ParquetWriter to avoid loading the
    whole range into memory. Handles day-boundary spans by iterating each
    day's DB file in turn. Missing day files are reported in skipped_days
    but do not fail the export.

    Raises ImportError if pyarrow is not installed.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    t0 = time.monotonic()

    schema = pa.schema(
        [
            ("timestamp", pa.timestamp("us", tz="UTC")),
            ("instrument_id", pa.string()),
            ("channel", pa.string()),
            ("value", pa.float64()),
            ("unit", pa.string()),
            ("status", pa.string()),
            ("experiment_id", pa.string()),
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = pq.ParquetWriter(
        str(output_path),
        schema,
        compression="snappy",
    )

    total_rows = 0
    skipped_days: list[str] = []
    archived_days: list[str] = []

    start_epoch = start_time.timestamp()
    end_epoch = end_time.timestamp()

    # A day whose SQLite file was rotated to cold Parquet (F17) has no daily DB;
    # its data lives only in the archive. Reuse ArchiveReader to read it back so
    # such days are exported, not silently dropped into skipped_days.
    reader = ArchiveReader(sqlite_root, sqlite_root / "archive")

    # Iterate daily DB files covering the range
    current_day = start_time.date()
    last_day = end_time.date()

    try:
        while current_day <= last_day:
            day_str = current_day.isoformat()
            db_path = sqlite_root / f"data_{day_str}.db"

            if not db_path.exists():
                cold_rows = _write_cold_day(
                    reader,
                    writer,
                    schema,
                    pa,
                    current_day,
                    start_time,
                    end_time,
                    chunk_size,
                )
                if cold_rows:
                    total_rows += cold_rows
                    archived_days.append(day_str)
                else:
                    # No daily DB and nothing in cold storage → genuinely no data.
                    skipped_days.append(day_str)
                current_day += timedelta(days=1)
                continue

            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(
                    "SELECT timestamp, instrument_id, channel, value, unit, status "
                    "FROM readings WHERE timestamp >= ? AND timestamp <= ? "
                    "ORDER BY timestamp",
                    (start_epoch, end_epoch),
                )

                while True:
                    rows = cursor.fetchmany(chunk_size)
                    if not rows:
                        break

                    timestamps = []
                    instrument_ids = []
                    channels = []
                    values = []
                    units = []
                    statuses = []
                    exp_ids = []

                    for row in rows:
                        ts_epoch = row["timestamp"]
                        timestamps.append(datetime.fromtimestamp(ts_epoch, tz=UTC))
                        instrument_ids.append(row["instrument_id"])
                        channels.append(row["channel"])
                        # NaN-доктрина: mask sentinel / error / legacy ±inf to NaN.
                        # The status column below preserves the discriminator; the
                        # archived value column never carries a non-physical number.
                        values.append(decode(float(row["value"]), row["status"]))
                        units.append(row["unit"])
                        statuses.append(row["status"])
                        exp_ids.append(experiment_id)

                    batch = pa.table(
                        {
                            "timestamp": pa.array(timestamps, type=pa.timestamp("us", tz="UTC")),
                            "instrument_id": pa.array(instrument_ids),
                            "channel": pa.array(channels),
                            "value": pa.array(values, type=pa.float64()),
                            "unit": pa.array(units),
                            "status": pa.array(statuses),
                            "experiment_id": pa.array(exp_ids),
                        },
                        schema=schema,
                    )
                    writer.write_table(batch)
                    total_rows += len(rows)

            finally:
                conn.close()

            current_day += timedelta(days=1)
    finally:
        writer.close()

    duration = time.monotonic() - t0
    file_size = output_path.stat().st_size if output_path.exists() else 0

    logger.info(
        "Parquet archive: %d rows, %.1f MB, %.1fs → %s",
        total_rows,
        file_size / 1e6,
        duration,
        output_path.name,
    )

    return ParquetExportResult(
        output_path=output_path,
        rows_written=total_rows,
        file_size_bytes=file_size,
        duration_s=duration,
        skipped_days=skipped_days,
        archived_days=archived_days,
    )


def _write_cold_day(
    reader: ArchiveReader,
    writer,
    schema,
    pa,
    day,
    start_time: datetime,
    end_time: datetime,
    chunk_size: int,
) -> int:
    """Stream a rotated day's cold-Parquet rows into the export writer.

    Returns the number of rows written (0 if the day has no cold data). Cold
    rows carry no experiment_id, so the exported column is null for them.
    query_rows is end-EXCLUSIVE and already NaN-decodes values; the window is
    clamped to this single day so a multi-day range never double-counts. The
    upper bound is nudged by 1 µs to keep the caller-visible `<= end_time`
    inclusivity of the hot-path SQL this mirrors.
    """
    day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    day_end_exclusive = day_start + timedelta(days=1)
    win_start = max(start_time, day_start)
    win_end = min(end_time + timedelta(microseconds=1), day_end_exclusive)

    rows = reader.query_rows(win_start, win_end, None)
    if not rows:
        return 0

    written = 0
    for offset in range(0, len(rows), chunk_size):
        chunk = rows[offset : offset + chunk_size]
        batch = pa.table(
            {
                "timestamp": pa.array(
                    [datetime.fromtimestamp(float(r[0]), tz=UTC) for r in chunk],
                    type=pa.timestamp("us", tz="UTC"),
                ),
                "instrument_id": pa.array([r[1] for r in chunk]),
                "channel": pa.array([r[2] for r in chunk]),
                # value is already NaN-decoded by query_rows — do not decode again.
                "value": pa.array([r[3] for r in chunk], type=pa.float64()),
                "unit": pa.array([r[4] for r in chunk]),
                "status": pa.array([r[5] for r in chunk]),
                # Cold rotation stores no experiment context → null column.
                "experiment_id": pa.array([None] * len(chunk), type=pa.string()),
            },
            schema=schema,
        )
        writer.write_table(batch)
        written += len(chunk)
    return written


def read_experiment_parquet(
    parquet_path: Path,
    channels: list[str] | None = None,
) -> dict[str, list[tuple[float, float]]]:
    """Read experiment data from Parquet. Returns {channel: [(unix_ts, value), ...]}.

    Empty dict if pyarrow not installed or file not found.
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        logger.warning("pyarrow not installed — cannot read Parquet")
        return {}

    if not parquet_path.exists():
        return {}

    try:
        table = pq.read_table(str(parquet_path))

        ts_col = table.column("timestamp")
        ts_us = ts_col.cast(pa.int64())
        ch_array = table.column("channel").to_pylist()
        val_array = table.column("value").to_pylist()
        status_array = table.column("status").to_pylist()

        channel_set = set(channels) if channels else None
        result: dict[str, list[tuple[float, float]]] = {}
        for i in range(table.num_rows):
            ch = ch_array[i]
            if channel_set is not None and ch not in channel_set:
                continue
            epoch = float(ts_us[i].as_py()) / 1_000_000.0
            # NaN-доктрина: mask legacy raw-inf / sentinel parquet rows on read.
            result.setdefault(ch, []).append((epoch, decode(float(val_array[i]), status_array[i])))

        return result

    except Exception:
        logger.exception("Failed to read Parquet: %s", parquet_path)
        return {}
