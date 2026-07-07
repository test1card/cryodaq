"""Unified read layer across SQLite (recent) and Parquet (archived) data.

ArchiveReader queries both sources transparently, using the archive index
to determine which daily files have been rotated to Parquet cold storage.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from cryodaq.storage.sentinel import decode
from cryodaq.storage.sqlite_writer import _parse_timestamp

logger = logging.getLogger(__name__)


def _ts_sort_key(raw: object) -> float:
    """Epoch-float sort key for mixed REAL/legacy-ISO timestamp values."""
    try:
        return _parse_timestamp(raw).timestamp()
    except (ValueError, TypeError, OSError):
        return float("inf")


def _day_from_db_name(name: str) -> str | None:
    """Extract the ``YYYY-MM-DD`` day from a ``data_YYYY-MM-DD.db`` filename."""
    day_part = name.removeprefix("data_")[:10]
    try:
        date.fromisoformat(day_part)
    except ValueError:
        return None
    return day_part


# Full row emitted by :meth:`ArchiveReader.query_rows` — value is already
# decoded (NaN-доктрина); status is the raw discriminator string.
FullRow = tuple[object, str, str, float, str, str]


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
            entry["original_name"]: entry["archive_path"] for entry in index.get("files", [])
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

    def query_rows(
        self,
        start: datetime | None,
        end: datetime | None,
        channels: list[str] | None,
        instrument_ids: list[str] | None = None,
    ) -> list[FullRow]:
        """Full readings rows across hot SQLite + cold Parquet for export.

        This is the read boundary for the CSV/XLSX date-range exporters: unlike
        :meth:`query` (which returns only ``{channel: [(ts, value)]}``), it
        preserves every export column ``(timestamp, instrument_id, channel,
        value, unit, status)``. Once a day is rotated to Parquet its SQLite file
        is gone, so exports MUST come here or they go blind over rotated days.

        Semantics mirror the SQLite exporters they replace: ``start`` inclusive,
        ``end`` **exclusive**; ``None`` bounds mean unbounded. ``value`` is
        decoded (a sentinel / error / legacy ±inf row surfaces as ``NaN``);
        ``status`` is returned verbatim. Rows are sorted by timestamp ascending.
        """
        channel_set = set(channels) if channels else None
        instrument_set = set(instrument_ids) if instrument_ids else None

        from_epoch = from_day = None
        to_epoch = to_day = None
        if start is not None:
            s = start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
            from_epoch, from_day = s.timestamp(), s.date()
        if end is not None:
            e = end.astimezone(UTC) if end.tzinfo else end.replace(tzinfo=UTC)
            to_epoch, to_day = e.timestamp(), e.date()

        index = self._load_index()
        # day → ("parquet", archive_rel) | ("sqlite", db_path). Archive wins:
        # after rotation the SQLite file is deleted, so the Parquet is canonical.
        sources: dict[str, tuple[str, str]] = {}
        for entry in index.get("files", []):
            day = _day_from_db_name(entry["original_name"])
            if day is not None:
                sources[day] = ("parquet", entry["archive_path"])
        if self._data_dir.exists():
            for db_path in self._data_dir.glob("data_????-??-??.db"):
                day = _day_from_db_name(db_path.name)
                if day is not None:
                    sources.setdefault(day, ("sqlite", str(db_path)))

        out: list[FullRow] = []
        for day_iso in sorted(sources):
            day = date.fromisoformat(day_iso)
            # end exclusive → a row on to_day may still precede to_epoch, so keep
            # the whole [from_day, to_day] day span; the row-level epoch filter
            # inside each reader makes the precise cut.
            if from_day is not None and day < from_day:
                continue
            if to_day is not None and day > to_day:
                continue
            kind, ref = sources[day_iso]
            if kind == "parquet":
                self._read_parquet_rows(ref, from_epoch, to_epoch, channel_set, instrument_set, out)
            else:
                self._read_sqlite_rows(Path(ref), from_epoch, to_epoch, channel_set, instrument_set, out)

        out.sort(key=lambda r: _ts_sort_key(r[0]))
        return out

    # ------------------------------------------------------------------
    # Source readers
    # ------------------------------------------------------------------

    def _read_sqlite_rows(
        self,
        db_path: Path,
        from_epoch: float | None,
        to_epoch: float | None,
        channels: set[str] | None,
        instruments: set[str] | None,
        out: list[FullRow],
    ) -> None:
        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                query = "SELECT timestamp, instrument_id, channel, value, unit, status FROM readings"
                cond: list[str] = []
                params: list[object] = []
                # Only bound the range when asked — a numeric bound would drop
                # legacy TEXT-ISO timestamps (SQLite orders TEXT above REAL).
                if from_epoch is not None:
                    cond.append("timestamp >= ?")
                    params.append(from_epoch)
                if to_epoch is not None:
                    cond.append("timestamp < ?")
                    params.append(to_epoch)
                if channels is not None:
                    ph = ",".join("?" * len(channels))
                    cond.append(f"channel IN ({ph})")
                    params.extend(channels)
                if instruments is not None:
                    ph = ",".join("?" * len(instruments))
                    cond.append(f"instrument_id IN ({ph})")
                    params.extend(instruments)
                if cond:
                    query += " WHERE " + " AND ".join(cond)
                query += " ORDER BY timestamp"
                for row in conn.execute(query, params):
                    out.append(
                        (
                            row["timestamp"],
                            str(row["instrument_id"]),
                            str(row["channel"]),
                            decode(float(row["value"]), row["status"]),
                            str(row["unit"]),
                            str(row["status"]),
                        )
                    )
            finally:
                conn.close()
        except Exception:
            logger.exception("Failed to read SQLite %s — partial result", db_path.name)

    def _read_parquet_rows(
        self,
        archive_rel: str,
        from_epoch: float | None,
        to_epoch: float | None,
        channels: set[str] | None,
        instruments: set[str] | None,
        out: list[FullRow],
    ) -> None:
        parquet_path = self._archive_dir / archive_rel
        if not parquet_path.exists():
            logger.warning("Archived Parquet file missing: %s — skipping", archive_rel)
            return
        try:
            import pyarrow.parquet as pq

            table = pq.read_table(
                str(parquet_path),
                columns=["timestamp", "instrument_id", "channel", "value", "unit", "status"],
            )
            ts_us = table.column("timestamp").cast("int64").to_pylist()
            inst_list = table.column("instrument_id").to_pylist()
            ch_list = table.column("channel").to_pylist()
            val_list = table.column("value").to_pylist()
            unit_list = table.column("unit").to_pylist()
            status_list = table.column("status").to_pylist()
            for ts_int, inst, ch, val, unit, status in zip(ts_us, inst_list, ch_list, val_list, unit_list, status_list):
                epoch = ts_int / 1_000_000.0
                if from_epoch is not None and epoch < from_epoch:
                    continue
                if to_epoch is not None and epoch >= to_epoch:
                    continue
                if channels is not None and ch not in channels:
                    continue
                if instruments is not None and inst not in instruments:
                    continue
                out.append((epoch, str(inst), str(ch), decode(float(val), status), str(unit), str(status)))
        except Exception:
            logger.exception("Failed to read Parquet %s — partial result", archive_rel)

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
                        f"SELECT timestamp, channel, value, status FROM readings "
                        f"WHERE timestamp >= ? AND timestamp <= ? "
                        f"AND channel IN ({placeholders}) ORDER BY timestamp",
                        (from_epoch, to_epoch, *channels),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT timestamp, channel, value, status FROM readings "
                        "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                        (from_epoch, to_epoch),
                    )
                for row in cursor:
                    ch = row["channel"]
                    # NaN-доктрина: mask sentinel / error / legacy ±inf at the read boundary.
                    out.setdefault(ch, []).append((float(row["timestamp"]), decode(float(row["value"]), row["status"])))
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
                columns=["timestamp", "channel", "value", "status"],
            )
            ts_us = table.column("timestamp").cast("int64").to_pylist()
            ch_list = table.column("channel").to_pylist()
            val_list = table.column("value").to_pylist()
            status_list = table.column("status").to_pylist()

            for ts_int, ch, val, status in zip(ts_us, ch_list, val_list, status_list):
                epoch = ts_int / 1_000_000.0
                if epoch < from_epoch or epoch > to_epoch:
                    continue
                if channels is not None and ch not in channels:
                    continue
                # NaN-доктрина: mask sentinel / error / legacy ±inf at the read boundary.
                out.setdefault(ch, []).append((epoch, decode(float(val), status)))
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
