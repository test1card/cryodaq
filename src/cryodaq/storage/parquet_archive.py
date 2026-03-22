"""Parquet export/read for experiment data archive.

Writes readings.parquet alongside measured_values.csv during experiment finalization.
pyarrow is OPTIONAL — functions degrade gracefully if not installed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def write_experiment_parquet(
    readings: list[dict[str, Any]],
    output_path: Path,
) -> Path | None:
    """Convert already-loaded readings to Parquet. Returns path or None.

    Args:
        readings: list of dicts with keys: timestamp (datetime), instrument_id,
                  channel, value, unit, status — same format as _load_experiment_readings().
        output_path: target .parquet file path.

    Returns:
        Path to written file, or None if pyarrow unavailable / empty / already exists.
    """
    if not readings:
        return None

    if output_path.exists():
        return output_path

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        logger.warning("pyarrow not installed — Parquet archive skipped")
        return None

    try:
        timestamps = [r["timestamp"] for r in readings]
        instrument_ids = [r.get("instrument_id", "") for r in readings]
        channels = [r.get("channel", "") for r in readings]
        values = [r.get("value", float("nan")) for r in readings]
        units = [r.get("unit", "") for r in readings]
        statuses = [r.get("status", "") for r in readings]

        table = pa.table({
            "timestamp": pa.array(timestamps, type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array(instrument_ids).dictionary_encode(),
            "channel": pa.array(channels).dictionary_encode(),
            "value": pa.array(values, type=pa.float64()),
            "unit": pa.array(units).dictionary_encode(),
            "status": pa.array(statuses).dictionary_encode(),
        })

        output_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            table,
            str(output_path),
            compression="zstd",
            compression_level=3,
            row_group_size=100_000,
        )
        logger.info("Parquet archive written: %s (%d rows)", output_path.name, len(readings))
        return output_path

    except Exception:
        logger.exception("Failed to write Parquet archive: %s", output_path)
        return None


def read_experiment_parquet(
    parquet_path: Path,
    channels: list[str] | None = None,
) -> dict[str, list[tuple[float, float]]]:
    """Read experiment data from Parquet. Returns {channel: [(unix_ts, value), ...]}.

    Args:
        parquet_path: path to readings.parquet file.
        channels: optional channel filter (predicate pushdown).

    Returns:
        Dict mapping channel name to list of (timestamp_epoch, value) tuples.
        Empty dict if pyarrow not installed or file not found.
    """
    try:
        import pyarrow.parquet as pq
    except ImportError:
        logger.warning("pyarrow not installed — cannot read Parquet")
        return {}

    if not parquet_path.exists():
        return {}

    try:
        filters = None
        if channels:
            import pyarrow.compute as pc
            filters = pc.field("channel").isin(channels)

        table = pq.read_table(str(parquet_path), filters=filters)

        ts_array = table.column("timestamp").to_pylist()
        ch_array = table.column("channel").to_pylist()
        val_array = table.column("value").to_pylist()

        result: dict[str, list[tuple[float, float]]] = {}
        for ts, ch, val in zip(ts_array, ch_array, val_array):
            epoch = ts.timestamp() if hasattr(ts, "timestamp") else float(ts)
            result.setdefault(ch, []).append((epoch, val))

        return result

    except Exception:
        logger.exception("Failed to read Parquet: %s", parquet_path)
        return {}
