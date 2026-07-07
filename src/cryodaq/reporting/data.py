from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryodaq.storage.archive_reader import ArchiveReader
from cryodaq.storage.sqlite_writer import _parse_timestamp

logger = logging.getLogger(__name__)


def _parse_archived_value(raw: Any) -> float:
    """Parse an archived CSV value cell → float, blank/unparseable → NaN.

    NaN-доктрина: a blank masked cell means "no reading", not a zero-valued
    measurement. Legacy archived CSVs lack a status column, so the blank cell
    itself is the only signal — decode it to NaN (renderers treat NaN as
    no-reading) rather than 0.0.
    """
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return float("nan")
    try:
        return float(text)
    except (TypeError, ValueError):
        return float("nan")


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
    run_records: list[dict[str, Any]] = field(default_factory=list)
    artifact_index: list[dict[str, Any]] = field(default_factory=list)
    result_tables: list[dict[str, Any]] = field(default_factory=list)
    summary_metadata: dict[str, Any] = field(default_factory=dict)


class ReportDataExtractor:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def load_metadata(self, metadata_path: Path) -> dict[str, Any]:
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    def load_dataset(self, metadata_path: Path) -> ReportDataset:
        metadata = self.load_metadata(metadata_path)
        experiment = metadata.get("experiment", {})
        start_time = self._parse_time(experiment.get("start_time"))
        end_time = self._parse_time(experiment.get("end_time")) or datetime.now(UTC)
        experiment_id = experiment.get("experiment_id")

        readings = self._load_archived_readings(metadata)
        if not readings:
            readings = self._load_readings(start_time, end_time)
        alarm_readings = [item for item in readings if item.channel.startswith("alarm/")]
        operator_log = self._load_operator_log(start_time, end_time, experiment_id)
        return ReportDataset(
            metadata=metadata,
            readings=readings,
            operator_log=operator_log,
            alarm_readings=alarm_readings,
            run_records=[
                dict(item) for item in metadata.get("run_records", []) if isinstance(item, dict)
            ],
            artifact_index=[
                dict(item) for item in metadata.get("artifact_index", []) if isinstance(item, dict)
            ],
            result_tables=[
                dict(item) for item in metadata.get("result_tables", []) if isinstance(item, dict)
            ],
            summary_metadata=dict(metadata.get("summary_metadata") or {}),
        )

    def _load_archived_readings(self, metadata: dict[str, Any]) -> list[HistoricalReading]:
        table_path = self._resolve_archived_table(metadata, table_id="measured_values")
        if table_path is None or not table_path.exists():
            return []
        rows: list[HistoricalReading] = []
        try:
            with table_path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    rows.append(
                        HistoricalReading(
                            timestamp=self._parse_time(row.get("timestamp")),
                            instrument_id=str(row.get("instrument_id") or ""),
                            channel=str(row.get("channel") or ""),
                            value=_parse_archived_value(row.get("value")),
                            unit=str(row.get("unit") or ""),
                            status=str(row.get("status") or ""),
                        )
                    )
        except Exception as exc:
            logger.warning("Failed to load archived measured values from %s: %s", table_path, exc)
            return []
        return rows

    def _resolve_archived_table(self, metadata: dict[str, Any], *, table_id: str) -> Path | None:
        for item in metadata.get("result_tables", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("table_id", "")).strip() != table_id:
                continue
            path = Path(str(item.get("path", "")).strip())
            if path.exists():
                return path
        artifact_root = Path(str(metadata.get("artifacts", {}).get("root_dir", "")).strip())
        fallback = artifact_root / "archive" / "tables" / f"{table_id}.csv"
        return fallback if fallback.exists() else None

    def _load_readings(self, start_time: datetime, end_time: datetime) -> list[HistoricalReading]:
        # Route through ArchiveReader: once cold rotation (F17) deletes an aged
        # daily SQLite file, its readings live only in Parquet, so a direct hot
        # scan would silently lose them when regenerating an old report.
        # query_rows unions hot SQLite + cold Parquet and already decodes the
        # NaN-доктрина sentinel (do NOT decode again here). archive_dir default
        # matches the CSV/XLSX exporters and cold_rotation (data_dir/"archive").
        # Semantics mirror those exporters: start inclusive, end exclusive (the
        # old direct scan was end-inclusive; no real report lands a reading on
        # the exact end microsecond), all channels, sorted by timestamp.
        rows = ArchiveReader(self._data_dir, self._data_dir / "archive").query_rows(
            start_time, end_time, None
        )
        return [
            HistoricalReading(
                timestamp=_parse_timestamp(raw_ts),
                instrument_id=str(instrument_id or ""),
                channel=str(channel or ""),
                value=value,
                unit=str(unit or ""),
                status=str(status or ""),
            )
            for raw_ts, instrument_id, channel, value, unit, status in rows
        ]

    def _load_operator_log(
        self,
        start_time: datetime,
        end_time: datetime,
        experiment_id: str | None,
    ) -> list[OperatorLogRecord]:
        # Route through ArchiveReader so a report over a >age_days-old experiment
        # still shows its operator journal: cold rotation (F17/CR-3) archives
        # operator_log to a companion Parquet and deletes the daily SQLite, so a
        # direct hot scan would go blind. query_operator_log unions hot + cold and
        # applies the inclusive time range; the experiment_id filter and tags
        # decode stay here so hot and cold rows behave identically.
        reader = ArchiveReader(self._data_dir, self._data_dir / "archive")
        rows: list[OperatorLogRecord] = []
        for raw_ts, exp_id, author, source, message, tags in reader.query_operator_log(
            start_time, end_time
        ):
            # Mirrors the old SQL `experiment_id = ? OR experiment_id IS NULL`.
            if experiment_id and not (exp_id == experiment_id or exp_id is None):
                continue
            rows.append(
                OperatorLogRecord(
                    timestamp=_parse_timestamp(raw_ts),
                    experiment_id=exp_id,
                    author=str(author or ""),
                    source=str(source or ""),
                    message=str(message or ""),
                    tags=tuple(json.loads(tags or "[]")),
                )
            )
        return rows

    @staticmethod
    def _parse_time(raw: Any) -> datetime:
        text = str(raw or "").strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
