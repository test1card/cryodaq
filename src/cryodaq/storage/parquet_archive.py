"""Parquet export/read for experiment data archive.

Phase 2e stage 1: export_experiment_readings_to_parquet() streams rows from
daily SQLite files into a single Parquet file during experiment finalization.

pyarrow is OPTIONAL — functions degrade gracefully if not installed.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_CHUNK_SIZE = 100_000


@dataclass
class ParquetExportResult:
    output_path: Path
    rows_written: int
    file_size_bytes: int
    duration_s: float
    skipped_days: list[str] = field(default_factory=list)


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

    schema = pa.schema([
        ("timestamp", pa.timestamp("us", tz="UTC")),
        ("instrument_id", pa.string()),
        ("channel", pa.string()),
        ("value", pa.float64()),
        ("unit", pa.string()),
        ("status", pa.string()),
        ("experiment_id", pa.string()),
    ])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = pq.ParquetWriter(
        str(output_path),
        schema,
        compression="snappy",
    )

    total_rows = 0
    skipped_days: list[str] = []

    start_epoch = start_time.timestamp()
    end_epoch = end_time.timestamp()

    # Iterate daily DB files covering the range
    current_day = start_time.date()
    last_day = end_time.date()

    try:
        while current_day <= last_day:
            day_str = current_day.isoformat()
            db_path = sqlite_root / f"data_{day_str}.db"

            if not db_path.exists():
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
                        timestamps.append(
                            datetime.fromtimestamp(ts_epoch, tz=UTC)
                        )
                        instrument_ids.append(row["instrument_id"])
                        channels.append(row["channel"])
                        values.append(float(row["value"]))
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
        total_rows, file_size / 1e6, duration, output_path.name,
    )

    return ParquetExportResult(
        output_path=output_path,
        rows_written=total_rows,
        file_size_bytes=file_size,
        duration_s=duration,
        skipped_days=skipped_days,
    )


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

        channel_set = set(channels) if channels else None
        result: dict[str, list[tuple[float, float]]] = {}
        for i in range(table.num_rows):
            ch = ch_array[i]
            if channel_set is not None and ch not in channel_set:
                continue
            epoch = float(ts_us[i].as_py()) / 1_000_000.0
            result.setdefault(ch, []).append((epoch, val_array[i]))

        return result

    except Exception:
        logger.exception("Failed to read Parquet: %s", parquet_path)
        return {}
