from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryodaq.storage.sqlite_writer import _parse_timestamp

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HistoricalReading:
    timestamp: datetime
    instrument_id: str
    channel: str
    value: float
    unit: str
    status: str


@dataclass(frozen=True, slots=True)
class OperatorLogRecord:
    timestamp: datetime
    experiment_id: str | None
    author: str
    source: str
    message: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReportDataset:
    metadata: dict[str, Any]
    readings: list[HistoricalReading] = field(default_factory=list)
    operator_log: list[OperatorLogRecord] = field(default_factory=list)
    alarm_readings: list[HistoricalReading] = field(default_factory=list)


class ReportDataExtractor:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def load_metadata(self, metadata_path: Path) -> dict[str, Any]:
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    def load_dataset(self, metadata_path: Path) -> ReportDataset:
        metadata = self.load_metadata(metadata_path)
        experiment = metadata.get("experiment", {})
        start_time = self._parse_time(experiment.get("start_time"))
        end_time = self._parse_time(experiment.get("end_time")) or datetime.now(timezone.utc)
        experiment_id = experiment.get("experiment_id")

        readings = self._load_readings(start_time, end_time)
        alarm_readings = [item for item in readings if item.channel.startswith("alarm/")]
        operator_log = self._load_operator_log(start_time, end_time, experiment_id)
        return ReportDataset(
            metadata=metadata,
            readings=readings,
            operator_log=operator_log,
            alarm_readings=alarm_readings,
        )

    def _db_paths(self, start_time: datetime, end_time: datetime) -> list[Path]:
        paths: list[Path] = []
        day = start_time.date()
        end_day = end_time.date()
        while day <= end_day:
            path = self._data_dir / f"data_{day.isoformat()}.db"
            if path.exists():
                paths.append(path)
            day = day + timedelta(days=1)
        return paths

    def _load_readings(self, start_time: datetime, end_time: datetime) -> list[HistoricalReading]:
        rows: list[HistoricalReading] = []
        for db_path in self._db_paths(start_time, end_time):
            conn = sqlite3.connect(str(db_path), timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                query = (
                    "SELECT timestamp, instrument_id, channel, value, unit, status "
                    "FROM readings WHERE timestamp >= ? AND timestamp <= ? "
                    "ORDER BY timestamp"
                )
                for row in conn.execute(query, (start_time.timestamp(), end_time.timestamp())).fetchall():
                    rows.append(
                        HistoricalReading(
                            timestamp=_parse_timestamp(row["timestamp"]),
                            instrument_id=str(row["instrument_id"] or ""),
                            channel=str(row["channel"] or ""),
                            value=float(row["value"]),
                            unit=str(row["unit"] or ""),
                            status=str(row["status"] or ""),
                        )
                    )
            except sqlite3.OperationalError:
                logger.info("readings table not found in %s", db_path.name)
            finally:
                conn.close()
        return rows

    def _load_operator_log(
        self,
        start_time: datetime,
        end_time: datetime,
        experiment_id: str | None,
    ) -> list[OperatorLogRecord]:
        rows: list[OperatorLogRecord] = []
        for db_path in self._db_paths(start_time, end_time):
            conn = sqlite3.connect(str(db_path), timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                query = (
                    "SELECT timestamp, experiment_id, author, source, message, tags "
                    "FROM operator_log WHERE timestamp >= ? AND timestamp <= ?"
                )
                params: list[Any] = [start_time.timestamp(), end_time.timestamp()]
                if experiment_id:
                    query += " AND (experiment_id = ? OR experiment_id IS NULL)"
                    params.append(experiment_id)
                query += " ORDER BY timestamp"
                for row in conn.execute(query, params).fetchall():
                    rows.append(
                        OperatorLogRecord(
                            timestamp=_parse_timestamp(row["timestamp"]),
                            experiment_id=row["experiment_id"],
                            author=str(row["author"] or ""),
                            source=str(row["source"] or ""),
                            message=str(row["message"] or ""),
                            tags=tuple(json.loads(row["tags"] or "[]")),
                        )
                    )
            except sqlite3.OperationalError:
                logger.info("operator_log table not found in %s", db_path.name)
            finally:
                conn.close()
        return rows

    @staticmethod
    def _parse_time(raw: Any) -> datetime:
        text = str(raw or "").strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
