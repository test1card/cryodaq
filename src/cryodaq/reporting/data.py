from __future__ import annotations

import csv
import json
import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from cryodaq.paths import get_archive_dir
from cryodaq.report_state import (
    ALLOWED_REPORT_INPUT_SUFFIXES,
    MAX_SOURCE_FILE_BYTES,
    MAX_SOURCE_TOTAL_BYTES,
    ReportContractError,
)
from cryodaq.storage.archive_reader import ArchiveReader, ArchiveUnavailableError
from cryodaq.storage.broker_replay import DescriptorReplayReader
from cryodaq.storage.descriptor_archive import ResolvedStorageDescriptor
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
    descriptor: ResolvedStorageDescriptor | None = None
    legacy: bool = True

    def __post_init__(self) -> None:
        descriptor = self.descriptor
        if descriptor is None:
            if self.legacy is not True:
                raise ValueError("a non-legacy report reading requires a descriptor")
            return
        if type(descriptor) is not ResolvedStorageDescriptor:
            raise TypeError("report descriptor must be exactly ResolvedStorageDescriptor")
        if self.legacy is not descriptor.legacy:
            raise ValueError("report legacy classification disagrees with descriptor")
        expected_channel = descriptor.display_name if descriptor.legacy else descriptor.channel_id
        if (self.instrument_id, self.channel, self.unit) != (
            descriptor.instrument_id,
            expected_channel,
            descriptor.unit,
        ):
            raise ValueError("report reading identity disagrees with descriptor")

    @property
    def grants_control_authority(self) -> bool:
        return False


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
    descriptor_complete: bool = True
    descriptor_issues: tuple[str, ...] = ()


class _ReadingsState(Enum):
    PROVEN_EMPTY = "proven_empty"
    PRESENT_READABLE = "present_readable"
    UNAVAILABLE_INCONSISTENT = "unavailable_inconsistent"


@dataclass(frozen=True, slots=True)
class _ReadingsResolution:
    state: _ReadingsState
    readings: tuple[HistoricalReading, ...] = ()
    detail: str = ""
    operator_log_proven_empty: bool = False


class ReportDataExtractor:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def load_metadata(self, metadata_path: Path) -> dict[str, Any]:
        if metadata_path.is_symlink() or not metadata_path.is_file():
            raise ReportContractError("metadata must be a regular file")
        if metadata_path.stat().st_size > MAX_SOURCE_FILE_BYTES:
            raise ReportContractError("metadata file is too large")
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    def load_dataset(self, metadata_path: Path) -> ReportDataset:
        metadata = self.load_metadata(metadata_path)
        self._validate_artifact_paths(metadata, metadata_path.parent)
        experiment = metadata.get("experiment", {})
        start_time = self._parse_time(experiment.get("start_time"))
        raw_end_time = experiment.get("end_time")
        end_time = self._parse_time(raw_end_time) if str(raw_end_time or "").strip() else datetime.now(UTC)
        experiment_id = experiment.get("experiment_id")

        resolution = self._resolve_readings(
            metadata,
            metadata_path.parent,
            start_time,
            end_time,
        )
        if resolution.state is _ReadingsState.UNAVAILABLE_INCONSISTENT:
            raise ReportContractError(f"measurement data unavailable or inconsistent: {resolution.detail}")
        readings = list(resolution.readings)
        # This synchronous compatibility reader has no descriptor envelope.
        # Legacy identifiers are deliberately not interpreted as event authority.
        alarm_readings = [
            item
            for item in readings
            if item.descriptor is not None and not item.descriptor.legacy and item.descriptor.role == "event"
        ]
        operator_log = self._load_operator_log(
            start_time,
            end_time,
            experiment_id,
            allow_proven_empty=resolution.operator_log_proven_empty,
        )
        return ReportDataset(
            metadata=metadata,
            readings=readings,
            operator_log=operator_log,
            alarm_readings=alarm_readings,
            run_records=[dict(item) for item in metadata.get("run_records", []) if isinstance(item, dict)],
            artifact_index=[dict(item) for item in metadata.get("artifact_index", []) if isinstance(item, dict)],
            result_tables=[dict(item) for item in metadata.get("result_tables", []) if isinstance(item, dict)],
            summary_metadata=dict(metadata.get("summary_metadata") or {}),
        )

    async def load_descriptor_dataset(self, metadata_path: Path) -> ReportDataset:
        """Load one report dataset bound to the bounded descriptor replay."""

        dataset = self.load_dataset(metadata_path)
        experiment = dataset.metadata["experiment"]
        start_time = self._parse_time(experiment.get("start_time"))
        raw_end_time = experiment.get("end_time")
        end_time = self._parse_time(raw_end_time) if str(raw_end_time or "").strip() else datetime.now(UTC)
        batch = await DescriptorReplayReader(self._data_dir).read_window(
            start=start_time,
            end=end_time,
        )

        from cryodaq.reporting.descriptor_projection import (
            bind_descriptor_projection,
            project_descriptor_replay,
        )

        return bind_descriptor_projection(dataset, project_descriptor_replay(batch))

    @staticmethod
    def _validate_artifact_paths(metadata: dict[str, Any], experiment_root: Path) -> None:
        """Reject metadata-controlled artifact paths outside the experiment jail."""
        root = experiment_root.resolve()
        total = 0
        for collection_name in ("artifact_index", "result_tables"):
            collection = metadata.get(collection_name, [])
            if not isinstance(collection, list):
                raise ReportContractError(f"{collection_name} must be a list")
            for item in collection:
                if not isinstance(item, dict):
                    continue
                raw = item.get("path")
                if raw in (None, ""):
                    continue
                if not isinstance(raw, str) or len(raw) > 4_096:
                    raise ReportContractError("artifact path must be a bounded string")
                candidate = Path(raw)
                if candidate.suffix.lower() not in ALLOWED_REPORT_INPUT_SUFFIXES:
                    raise ReportContractError("artifact path has an unsupported extension")
                if not candidate.is_absolute():
                    candidate = root / candidate
                if candidate.is_symlink():
                    raise ReportContractError("artifact path must not be a symlink")
                resolved = candidate.resolve()
                if resolved != root and root not in resolved.parents:
                    raise ReportContractError("artifact path escapes the experiment root")
                if not resolved.exists():
                    raise ReportContractError("artifact path must exist")
                if not resolved.is_file():
                    raise ReportContractError("artifact path must reference a regular file")
                size = resolved.stat().st_size
                if size > MAX_SOURCE_FILE_BYTES:
                    raise ReportContractError("artifact input is too large")
                total += size
                if total > MAX_SOURCE_TOTAL_BYTES:
                    raise ReportContractError("artifact inputs exceed total size limit")
                item["path"] = str(resolved)

    def _load_archived_readings(
        self,
        metadata: dict[str, Any],
        experiment_root: Path | None = None,
    ) -> list[HistoricalReading]:
        experiment_root = experiment_root or self._data_dir
        table_path = self._resolve_archived_table(
            metadata,
            experiment_root=experiment_root,
            table_id="measured_values",
        )
        if table_path is None or not table_path.exists():
            return []
        rows: list[HistoricalReading] = []
        try:
            with table_path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                required = {"timestamp", "instrument_id", "channel", "value", "unit"}
                if not required <= set(reader.fieldnames or ()):
                    raise ValueError("measured values columns are incomplete")
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
            raise ReportContractError("archived measured values table is unreadable") from exc
        return rows

    def _resolve_readings(
        self,
        metadata: dict[str, Any],
        experiment_root: Path,
        start_time: datetime,
        end_time: datetime,
    ) -> _ReadingsResolution:
        """Resolve measurements without conflating an empty result with damage."""
        summary = metadata.get("summary_metadata")
        if isinstance(summary, dict):
            if summary.get("measured_values_complete") is False:
                return _ReadingsResolution(
                    _ReadingsState.UNAVAILABLE_INCONSISTENT,
                    detail="finalized metadata declares measured values incomplete",
                )
            if summary.get("measured_values_truncated") is True:
                return _ReadingsResolution(
                    _ReadingsState.UNAVAILABLE_INCONSISTENT,
                    detail="finalized metadata declares measured values truncated",
                )
            if summary.get("measured_values_issues"):
                return _ReadingsResolution(
                    _ReadingsState.UNAVAILABLE_INCONSISTENT,
                    detail="finalized metadata records measured value issues",
                )
        counts = self._declared_measurement_counts(metadata)
        archive_path = self._resolve_archived_table(
            metadata,
            experiment_root=experiment_root,
            table_id="measured_values",
        )
        if archive_path is not None:
            try:
                readings = self._load_archived_readings(metadata, experiment_root)
            except ReportContractError as exc:
                return _ReadingsResolution(
                    _ReadingsState.UNAVAILABLE_INCONSISTENT,
                    detail=str(exc),
                )
            if readings:
                if counts and not self._counts_match(counts, len(readings)):
                    return _ReadingsResolution(
                        _ReadingsState.UNAVAILABLE_INCONSISTENT,
                        detail="readable archive row count contradicts finalized metadata",
                    )
                return _ReadingsResolution(
                    _ReadingsState.PRESENT_READABLE,
                    tuple(readings),
                )
            if counts and not self._counts_match(counts, 0):
                return _ReadingsResolution(
                    _ReadingsState.UNAVAILABLE_INCONSISTENT,
                    detail="readable archive row count contradicts finalized metadata",
                )
            operator_log_proven_empty, detail = self._verify_empty_source_context(
                metadata,
                start_time,
                end_time,
            )
            if detail:
                return _ReadingsResolution(
                    _ReadingsState.UNAVAILABLE_INCONSISTENT,
                    detail=detail,
                )
            return _ReadingsResolution(
                _ReadingsState.PRESENT_READABLE,
                operator_log_proven_empty=operator_log_proven_empty,
            )

        if self._proves_empty_measurements(metadata, counts):
            operator_log_proven_empty, detail = self._verify_empty_source_context(
                metadata,
                start_time,
                end_time,
            )
            if detail:
                return _ReadingsResolution(
                    _ReadingsState.UNAVAILABLE_INCONSISTENT,
                    detail=detail,
                )
            return _ReadingsResolution(
                _ReadingsState.PROVEN_EMPTY,
                operator_log_proven_empty=operator_log_proven_empty,
            )
        if counts and not self._counts_match(counts, 0):
            return _ReadingsResolution(
                _ReadingsState.UNAVAILABLE_INCONSISTENT,
                detail="declared measurement archive is missing",
            )

        try:
            readings = self._load_readings(start_time, end_time)
        except ArchiveUnavailableError as exc:
            return _ReadingsResolution(
                _ReadingsState.UNAVAILABLE_INCONSISTENT,
                detail=str(exc),
            )
        if readings:
            if counts and not self._counts_match(counts, len(readings)):
                return _ReadingsResolution(
                    _ReadingsState.UNAVAILABLE_INCONSISTENT,
                    detail="live measurement row count contradicts finalized metadata",
                )
            return _ReadingsResolution(
                _ReadingsState.PRESENT_READABLE,
                tuple(readings),
            )
        return _ReadingsResolution(
            _ReadingsState.UNAVAILABLE_INCONSISTENT,
            detail="zero rows lack finalized complete measurement authority",
        )

    def _verify_empty_source_context(
        self,
        metadata: dict[str, Any],
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[bool, str]:
        reader = ArchiveReader(self._data_dir, get_archive_dir(self._data_dir))
        try:
            lifecycle_only, operator_log_absent = self._finalized_lifecycle_only(
                reader,
                metadata,
                start_time,
                end_time,
            )
        except ArchiveUnavailableError as exc:
            return False, str(exc)
        if lifecycle_only:
            return operator_log_absent, ""
        try:
            readings = self._load_readings(start_time, end_time)
        except ArchiveUnavailableError as exc:
            return False, str(exc)
        if readings:
            return False, "zero-row metadata contradicts a readable measurement source"
        return False, ""

    def _finalized_lifecycle_only(
        self,
        reader: ArchiveReader,
        metadata: dict[str, Any],
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[bool, bool]:
        """Qualify experiment-only SQLite; all other schemas use strict readers."""
        if reader._load_index().get("files"):
            return False, False
        experiment = metadata["experiment"]
        expected = (
            experiment.get("experiment_id"),
            experiment.get("status"),
            str(experiment.get("start_time") or ""),
            str(experiment.get("end_time") or ""),
        )
        matched = False
        operator_log_absent = True
        for db_path in self._data_dir.glob("data_????-??-??.db"):
            try:
                day = datetime.strptime(db_path.stem.removeprefix("data_"), "%Y-%m-%d").date()
            except ValueError:
                continue
            if day < start_time.date() or day > end_time.date():
                continue
            if db_path.is_symlink() or not db_path.is_file():
                return False, False
            try:
                with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
                    if conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
                        return False, False
                    tables = {
                        str(row[0])
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                        )
                    }
                    if "experiments" not in tables or not tables <= {"experiments", "operator_log"}:
                        return False, False
                    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(experiments)")}
                    if not {"experiment_id", "status", "start_time", "end_time"} <= columns:
                        return False, False
                    rows = conn.execute(
                        "SELECT experiment_id, status, start_time, end_time FROM experiments WHERE experiment_id = ?",
                        (expected[0],),
                    ).fetchall()
                    if rows != [expected]:
                        return False, False
                    operator_log_absent = operator_log_absent and "operator_log" not in tables
            except sqlite3.Error:
                return False, False
            matched = True
        return matched, matched and operator_log_absent

    @staticmethod
    def _declared_measurement_counts(metadata: dict[str, Any]) -> tuple[object, ...]:
        counts: list[object] = []
        summary = metadata.get("summary_metadata")
        if isinstance(summary, dict) and "measured_value_rows" in summary:
            counts.append(summary["measured_value_rows"])
        for item in metadata.get("result_tables", []):
            if (
                isinstance(item, dict)
                and str(item.get("table_id", "")).strip() == "measured_values"
                and "row_count" in item
            ):
                counts.append(item["row_count"])
        for item in metadata.get("artifact_index", []):
            if not isinstance(item, dict):
                continue
            raw_path = str(item.get("path", ""))
            if item.get("role") != "measured_values" and Path(raw_path).name != "measured_values.csv":
                continue
            artifact_summary = item.get("summary")
            if isinstance(artifact_summary, dict) and "rows" in artifact_summary:
                counts.append(artifact_summary["rows"])
        return tuple(counts)

    @staticmethod
    def _counts_match(counts: tuple[object, ...], expected: int) -> bool:
        return all(type(count) is int and count == expected for count in counts)

    @classmethod
    def _proves_empty_measurements(
        cls,
        metadata: dict[str, Any],
        counts: tuple[object, ...],
    ) -> bool:
        experiment = metadata.get("experiment")
        summary = metadata.get("summary_metadata")
        return (
            isinstance(experiment, dict)
            and experiment.get("status") in {"COMPLETED", "ABORTED"}
            and bool(str(experiment.get("end_time") or "").strip())
            and isinstance(summary, dict)
            and type(summary.get("measured_value_rows")) is int
            and summary["measured_value_rows"] == 0
            and summary.get("measured_values_complete") is True
            and summary.get("measured_values_truncated") is False
            and type(summary.get("measured_values_issues")) is list
            and not summary["measured_values_issues"]
            and cls._counts_match(counts, 0)
        )

    def _resolve_archived_table(
        self,
        metadata: dict[str, Any],
        *,
        experiment_root: Path,
        table_id: str,
    ) -> Path | None:
        root = experiment_root.resolve()

        def safe_csv(path: Path) -> Path | None:
            if path.suffix.lower() != ".csv" or path.is_symlink():
                return None
            try:
                resolved = path.resolve()
            except OSError:
                return None
            if resolved != root and root not in resolved.parents:
                return None
            return resolved if resolved.is_file() else None

        for item in metadata.get("result_tables", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("table_id", "")).strip() != table_id:
                continue
            path = Path(str(item.get("path", "")).strip())
            if safe := safe_csv(path):
                return safe
        return safe_csv(root / "archive" / "tables" / f"{table_id}.csv")

    def _load_readings(self, start_time: datetime, end_time: datetime) -> list[HistoricalReading]:
        # Route through ArchiveReader: once cold rotation (F17) deletes an aged
        # daily SQLite file, its readings live only in Parquet, so a direct hot
        # scan would silently lose them when regenerating an old report.
        # query_rows unions hot SQLite + cold Parquet and already decodes the
        # NaN-доктрина sentinel (do NOT decode again here). Resolve archive_dir
        # through the migration-aware authority shared with exporters/rotation.
        # Semantics mirror those exporters: start inclusive, end exclusive (the
        # old direct scan was end-inclusive; no real report lands a reading on
        # the exact end microsecond), all channels, sorted by timestamp.
        rows = ArchiveReader(self._data_dir, get_archive_dir(self._data_dir)).query_rows(
            start_time,
            end_time,
            None,
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
        *,
        allow_proven_empty: bool = False,
    ) -> list[OperatorLogRecord]:
        # Route through ArchiveReader so a report over a >age_days-old experiment
        # still shows its operator journal: cold rotation (F17/CR-3) archives
        # operator_log to a companion Parquet and deletes the daily SQLite, so a
        # direct hot scan would go blind. query_operator_log unions hot + cold and
        # applies the inclusive time range; the experiment_id filter and tags
        # decode stay here so hot and cold rows behave identically.
        reader = ArchiveReader(self._data_dir, get_archive_dir(self._data_dir))
        rows: list[OperatorLogRecord] = []
        try:
            archived_rows = reader.query_operator_log(start_time, end_time)
        except ArchiveUnavailableError:
            if allow_proven_empty:
                return []
            raise
        for raw_ts, exp_id, author, source, message, tags in archived_rows:
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
