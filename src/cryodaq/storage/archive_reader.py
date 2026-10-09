"""Unified read layer across SQLite (recent) and Parquet (archived) data.

ArchiveReader queries both sources transparently, using the archive index
to determine which daily files have been rotated to Parquet cold storage.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class ArchiveReader:
    """Read channel data spanning SQLite (recent) + Parquet (cold archive).

    Parameters
    ----------
    data_dir:
        Directory containing daily ``data_YYYY-MM-DD.db`` SQLite files.
    archive_dir:
        Directory containing ``index.json`` and Parquet files.
    """

    def __init__(self, data_dir: Path, archive_dir: Path) -> None:
        self._data_dir = data_dir
        self._archive_dir = archive_dir

    def query(
        self,
        channels: list[str] | None,
        from_ts: datetime,
        to_ts: datetime,
    ) -> dict[str, list[tuple[float, float]]]:
        """Return readings in [from_ts, to_ts] from both SQLite and Parquet.

        Returns
        -------
        dict[str, list[tuple[float, float]]]
            ``{channel: [(unix_ts, value), ...]}`` sorted by timestamp ascending.
        """
        channel_set = set(channels) if channels is not None else None
        index = self._load_index()
        archived_names: dict[str, str] = {
            entry["original_name"]: entry["archive_path"]
            for entry in index.get("files", [])
        }

        result: dict[str, list[tuple[float, float]]] = {}

        # Normalize to UTC first so epoch values and day boundaries are consistent.
        from_utc = from_ts.astimezone(UTC) if from_ts.tzinfo else from_ts.replace(tzinfo=UTC)
        to_utc = to_ts.astimezone(UTC) if to_ts.tzinfo else to_ts.replace(tzinfo=UTC)

        from_epoch = from_utc.timestamp()
        to_epoch = to_utc.timestamp()

        # Iterate day by day across the query range
        current_day = from_utc.date()
        last_day = to_utc.date()
        while current_day <= last_day:
            db_name = f"data_{current_day.isoformat()}.db"
            if db_name in archived_names:
                self._query_parquet(
                    archived_names[db_name],
                    from_epoch,
                    to_epoch,
                    channel_set,
                    result,
                )
            else:
                db_path = self._data_dir / db_name
                if db_path.exists():
                    self._query_sqlite(db_path, from_epoch, to_epoch, channel_set, result)
            current_day += timedelta(days=1)

        # Sort each channel's data by timestamp
        for ch in result:
            result[ch].sort(key=lambda x: x[0])

        return result

    # ------------------------------------------------------------------
    # Source readers
    # ------------------------------------------------------------------

    def _query_sqlite(
        self,
        db_path: Path,
        from_epoch: float,
        to_epoch: float,
        channels: set[str] | None,
        out: dict[str, list[tuple[float, float]]],
    ) -> None:
        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                if channels is not None:
                    placeholders = ",".join("?" * len(channels))
                    cursor = conn.execute(
                        f"SELECT timestamp, channel, value FROM readings "
                        f"WHERE timestamp >= ? AND timestamp <= ? "
                        f"AND channel IN ({placeholders}) ORDER BY timestamp",
                        (from_epoch, to_epoch, *channels),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT timestamp, channel, value FROM readings "
                        "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                        (from_epoch, to_epoch),
                    )
                for row in cursor:
                    ch = row["channel"]
                    out.setdefault(ch, []).append((float(row["timestamp"]), float(row["value"])))
            finally:
                conn.close()
        except Exception:
            logger.exception("Failed to read SQLite %s — partial result", db_path.name)

    def _query_parquet(
        self,
        archive_rel: str,
        from_epoch: float,
        to_epoch: float,
        channels: set[str] | None,
        out: dict[str, list[tuple[float, float]]],
    ) -> None:
        parquet_path = self._archive_dir / archive_rel
        if not parquet_path.exists():
            logger.warning("Archived Parquet file missing: %s — skipping", archive_rel)
            return
        try:
            import pyarrow.parquet as pq

            table = pq.read_table(
                str(parquet_path),
                columns=["timestamp", "channel", "value"],
            )
            ts_us = table.column("timestamp").cast("int64").to_pylist()
            ch_list = table.column("channel").to_pylist()
            val_list = table.column("value").to_pylist()

            for ts_int, ch, val in zip(ts_us, ch_list, val_list):
                epoch = ts_int / 1_000_000.0
                if epoch < from_epoch or epoch > to_epoch:
                    continue
                if channels is not None and ch not in channels:
                    continue
                out.setdefault(ch, []).append((epoch, float(val)))
        except Exception:
            logger.exception("Failed to read Parquet %s — partial result", archive_rel)

    # ------------------------------------------------------------------
    # Index helpers
    # ------------------------------------------------------------------

    def _load_index(self) -> dict:
        index_path = self._archive_dir / "index.json"
        if not index_path.exists():
            return {"files": []}
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            logger.error(
                "Archive index.json at %s is corrupt — query cannot determine which days "
                "have been rotated to Parquet. Inspect and repair or delete the file manually.",
                index_path,
            )
            raise RuntimeError(f"Archive index.json corrupt: {index_path}")
