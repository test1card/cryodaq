"""Experiment templates, lifecycle metadata, and artifact persistence."""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SCHEMA_EXPERIMENTS = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id    TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    operator         TEXT NOT NULL,
    cryostat         TEXT NOT NULL DEFAULT '',
    sample           TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT '',
    start_time       TEXT NOT NULL,
    end_time         TEXT,
    status           TEXT NOT NULL DEFAULT 'RUNNING',
    config_snapshot  TEXT NOT NULL DEFAULT '{}',
    template_id      TEXT NOT NULL DEFAULT 'custom',
    title            TEXT NOT NULL DEFAULT '',
    notes            TEXT NOT NULL DEFAULT '',
    custom_fields    TEXT NOT NULL DEFAULT '{}',
    report_enabled   INTEGER NOT NULL DEFAULT 1,
    artifact_dir     TEXT NOT NULL DEFAULT '',
    metadata_path    TEXT NOT NULL DEFAULT '',
    sections         TEXT NOT NULL DEFAULT '[]',
    retroactive      INTEGER NOT NULL DEFAULT 0
);
"""


class ExperimentStatus(Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class ExperimentPhase(str, Enum):
    PREPARATION = "preparation"
    VACUUM = "vacuum"
    COOLDOWN = "cooldown"
    MEASUREMENT = "measurement"
    WARMUP = "warmup"
    TEARDOWN = "teardown"


class AppMode(Enum):
    DEBUG = "debug"
    EXPERIMENT = "experiment"


@dataclass(frozen=True, slots=True)
class TemplateField:
    id: str
    label: str
    default: str = ""


@dataclass(frozen=True, slots=True)
class ExperimentTemplate:
    template_id: str
    name: str
    sections: tuple[str, ...]
    report_enabled: bool
    report_sections: tuple[str, ...] = ()
    custom_fields: tuple[TemplateField, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.template_id,
            "name": self.name,
            "sections": list(self.sections),
            "report_enabled": self.report_enabled,
            "report_sections": list(self.report_sections),
            "custom_fields": [asdict(field) for field in self.custom_fields],
        }


@dataclass(frozen=True, slots=True)
class ExperimentInfo:
    experiment_id: str
    name: str
    title: str
    template_id: str
    operator: str
    cryostat: str
    sample: str
    description: str
    notes: str
    start_time: datetime
    end_time: datetime | None
    status: ExperimentStatus
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    custom_fields: dict[str, str] = field(default_factory=dict)
    report_enabled: bool = True
    sections: tuple[str, ...] = ()
    artifact_dir: Path | None = None
    metadata_path: Path | None = None
    retroactive: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "title": self.title,
            "template_id": self.template_id,
            "operator": self.operator,
            "cryostat": self.cryostat,
            "sample": self.sample,
            "description": self.description,
            "notes": self.notes,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status.value,
            "config_snapshot": self.config_snapshot,
            "custom_fields": dict(self.custom_fields),
            "report_enabled": self.report_enabled,
            "sections": list(self.sections),
            "artifact_dir": str(self.artifact_dir) if self.artifact_dir else "",
            "metadata_path": str(self.metadata_path) if self.metadata_path else "",
            "retroactive": self.retroactive,
        }


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    experiment_id: str
    title: str
    template_id: str
    template_name: str
    operator: str
    sample: str
    status: str
    start_time: datetime
    end_time: datetime | None
    artifact_dir: Path
    metadata_path: Path
    docx_path: Path | None
    pdf_path: Path | None
    report_enabled: bool
    report_present: bool
    notes: str
    retroactive: bool
    run_record_count: int = 0
    artifact_count: int = 0
    result_table_count: int = 0
    run_records: tuple[dict[str, Any], ...] = ()
    artifact_index: tuple[dict[str, Any], ...] = ()
    result_tables: tuple[dict[str, Any], ...] = ()
    summary_metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "title": self.title,
            "template_id": self.template_id,
            "template_name": self.template_name,
            "operator": self.operator,
            "sample": self.sample,
            "status": self.status,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "artifact_dir": str(self.artifact_dir),
            "metadata_path": str(self.metadata_path),
            "docx_path": str(self.docx_path) if self.docx_path else "",
            "pdf_path": str(self.pdf_path) if self.pdf_path else "",
            "report_enabled": self.report_enabled,
            "report_present": self.report_present,
            "notes": self.notes,
            "retroactive": self.retroactive,
            "run_record_count": self.run_record_count,
            "artifact_count": self.artifact_count,
            "result_table_count": self.result_table_count,
            "run_records": [dict(item) for item in self.run_records],
            "artifact_index": [dict(item) for item in self.artifact_index],
            "result_tables": [dict(item) for item in self.result_tables],
            "summary_metadata": dict(self.summary_metadata),
        }


@dataclass(frozen=True, slots=True)
class ExperimentState:
    app_mode: AppMode
    active_experiment_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "app_mode": self.app_mode.value,
            "active_experiment_id": self.active_experiment_id,
        }


@dataclass(frozen=True, slots=True)
class RunRecord:
    record_id: str
    source_run_id: str
    source_tab: str
    source_module: str
    run_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    result_summary: dict[str, Any] = field(default_factory=dict)
    artifact_paths: tuple[str, ...] = ()
    experiment_context: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source_run_id": self.source_run_id,
            "source_tab": self.source_tab,
            "source_module": self.source_module,
            "run_type": self.run_type,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "parameters": dict(self.parameters),
            "result_summary": dict(self.result_summary),
            "artifact_paths": list(self.artifact_paths),
            "experiment_context": dict(self.experiment_context),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> RunRecord:
        return cls(
            record_id=_clean_text(payload.get("record_id")) or uuid.uuid4().hex[:12],
            source_run_id=_clean_text(payload.get("source_run_id")),
            source_tab=_clean_text(payload.get("source_tab")),
            source_module=_clean_text(payload.get("source_module")),
            run_type=_clean_text(payload.get("run_type")),
            status=_clean_text(payload.get("status")) or "UNKNOWN",
            started_at=_parse_time(payload.get("started_at")) or datetime.now(UTC),
            finished_at=_parse_time(payload.get("finished_at")),
            parameters=dict(payload.get("parameters") or {}),
            result_summary=dict(payload.get("result_summary") or {}),
            artifact_paths=tuple(
                str(item).strip() for item in payload.get("artifact_paths", []) if str(item).strip()
            ),
            experiment_context=dict(payload.get("experiment_context") or {}),
        )


def _parse_time(raw: datetime | str | None) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=UTC)
        return raw.astimezone(UTC)
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_custom_fields(raw: dict[str, Any] | None) -> dict[str, str]:
    if not raw:
        return {}
    return {str(key): str(value) for key, value in raw.items() if str(key).strip()}


def _clean_text(raw: Any) -> str:
    if raw is None:
        return ""
    return str(raw).strip()


class ExperimentManager:
    def __init__(
        self,
        data_dir: Path,
        instruments_config: Path,
        *,
        templates_dir: Path | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._instruments_config = instruments_config
        self._templates_dir = templates_dir
        self._artifacts_dir = self._data_dir / "experiments"
        self._state_path = self._data_dir / "experiment_state.json"
        self._active: ExperimentInfo | None = None
        self._state = ExperimentState(app_mode=AppMode.EXPERIMENT)
        self._templates_cache: dict[str, ExperimentTemplate] | None = None
        self._load_state()

    @property
    def active_experiment(self) -> ExperimentInfo | None:
        return self._active

    @property
    def app_mode(self) -> AppMode:
        return self._state.app_mode

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def active_experiment_id(self) -> str | None:
        return self._active.experiment_id if self._active is not None else None

    def get_templates(self) -> list[ExperimentTemplate]:
        if self._templates_cache is None:
            self._templates_cache = self._load_templates()
        return sorted(self._templates_cache.values(), key=lambda item: item.name.lower())

    def get_template(self, template_id: str) -> ExperimentTemplate:
        templates = {template.template_id: template for template in self.get_templates()}
        if template_id not in templates:
            raise KeyError(f"Unknown experiment template '{template_id}'.")
        return templates[template_id]

    def get_status_payload(self) -> dict[str, Any]:
        return {
            "ok": True,
            "app_mode": self.app_mode.value,
            "active_experiment": self._active.to_payload() if self._active else None,
            "current_phase": self.get_current_phase(),
            "run_records": [record.to_payload() for record in self.list_run_records(active_only=True)],
            "templates": [template.to_payload() for template in self.get_templates()],
        }

    def get_app_mode(self) -> AppMode:
        return self.app_mode

    def set_app_mode(self, mode: AppMode | str) -> AppMode:
        next_mode = self._normalize_app_mode(mode)
        if next_mode is AppMode.DEBUG and self._active is not None:
            raise RuntimeError("Cannot switch to debug mode while an experiment card is still active.")
        if next_mode == self._state.app_mode:
            return self._state.app_mode
        self._state = ExperimentState(
            app_mode=next_mode,
            active_experiment_id=self._state.active_experiment_id,
        )
        self._write_state()
        return self._state.app_mode

    def list_archive_entries(
        self,
        *,
        template_id: str | None = None,
        operator: str | None = None,
        sample: str | None = None,
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
        report_present: bool | None = None,
        sort_by: str = "start_time",
        descending: bool = True,
    ) -> list[ArchiveEntry]:
        start_dt = _parse_time(start_date)
        end_dt = _parse_time(end_date)
        # Date-only input (00:00:00) → make inclusive: include entire selected day
        if end_dt and end_dt.hour == 0 and end_dt.minute == 0 and end_dt.second == 0:
            from datetime import timedelta
            end_dt = end_dt + timedelta(days=1)
        entries: list[ArchiveEntry] = []
        if not self._artifacts_dir.exists():
            return entries

        for metadata_path in sorted(self._artifacts_dir.glob("*/metadata.json")):
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                experiment = payload.get("experiment", {})
                template = payload.get("template", {})
                run_records = tuple(
                    dict(item) for item in payload.get("run_records", []) if isinstance(item, dict)
                )
                artifact_index = tuple(
                    dict(item) for item in payload.get("artifact_index", []) if isinstance(item, dict)
                )
                result_tables = tuple(
                    dict(item) for item in payload.get("result_tables", []) if isinstance(item, dict)
                )
                artifact_dir = metadata_path.parent
                docx_path = artifact_dir / "reports" / "report_editable.docx"
                if not docx_path.exists():
                    docx_path = artifact_dir / "reports" / "report.docx"
                pdf_path = artifact_dir / "reports" / "report_raw.pdf"
                if not pdf_path.exists():
                    pdf_path = artifact_dir / "reports" / "report.pdf"
                entry = ArchiveEntry(
                    experiment_id=_clean_text(experiment.get("experiment_id")),
                    title=_clean_text(experiment.get("title") or experiment.get("name")),
                    template_id=_clean_text(experiment.get("template_id") or template.get("id")),
                    template_name=_clean_text(template.get("name") or experiment.get("template_id")),
                    operator=_clean_text(experiment.get("operator")),
                    sample=_clean_text(experiment.get("sample")),
                    status=_clean_text(experiment.get("status")),
                    start_time=_parse_time(experiment.get("start_time")) or datetime.now(UTC),
                    end_time=_parse_time(experiment.get("end_time")),
                    artifact_dir=artifact_dir,
                    metadata_path=metadata_path,
                    docx_path=docx_path if docx_path.exists() else None,
                    pdf_path=pdf_path if pdf_path.exists() else None,
                    report_enabled=bool(experiment.get("report_enabled", True)),
                    report_present=docx_path.exists() or pdf_path.exists(),
                    notes=_clean_text(experiment.get("notes")),
                    retroactive=bool(experiment.get("retroactive", False)),
                    run_record_count=len(run_records),
                    artifact_count=len(artifact_index),
                    result_table_count=len(result_tables),
                    run_records=run_records,
                    artifact_index=artifact_index,
                    result_tables=result_tables,
                    summary_metadata=dict(payload.get("summary_metadata") or {}),
                )
            except Exception as exc:
                logger.warning("Failed to load archive metadata %s: %s", metadata_path, exc)
                continue
            if entry.status == ExperimentStatus.RUNNING.value:
                continue

            if template_id and entry.template_id != template_id:
                continue
            if operator and operator.lower() not in entry.operator.lower():
                continue
            if sample and sample.lower() not in entry.sample.lower():
                continue
            if start_dt and entry.start_time < start_dt:
                continue
            if end_dt and entry.start_time > end_dt:
                continue
            if report_present is not None and entry.report_present != report_present:
                continue
            entries.append(entry)

        sort_key_map = {
            "start_time": lambda item: item.start_time,
            "operator": lambda item: item.operator.lower(),
            "sample": lambda item: item.sample.lower(),
            "template": lambda item: item.template_name.lower(),
            "title": lambda item: item.title.lower(),
        }
        key_fn = sort_key_map.get(sort_by, sort_key_map["start_time"])
        entries.sort(key=key_fn, reverse=descending)
        return entries

    def get_archive_item(self, experiment_id: str) -> ArchiveEntry | None:
        experiment_id = _clean_text(experiment_id)
        if not experiment_id:
            raise ValueError("experiment_id is required.")
        for entry in self.list_archive_entries(descending=True):
            if entry.experiment_id == experiment_id:
                return entry
        return None

    def attach_run_record(
        self,
        *,
        source_tab: str,
        source_module: str,
        run_type: str,
        status: str,
        started_at: datetime | str,
        finished_at: datetime | str | None = None,
        parameters: dict[str, Any] | None = None,
        result_summary: dict[str, Any] | None = None,
        artifact_paths: list[str] | tuple[str, ...] | None = None,
        source_run_id: str | None = None,
        experiment_id: str | None = None,
    ) -> RunRecord | None:
        if self.app_mode is not AppMode.EXPERIMENT:
            return None
        active = self._active
        if active is None:
            return None
        if experiment_id is not None and experiment_id != active.experiment_id:
            raise ValueError(
                f"experiment_id '{experiment_id}' does not match active '{active.experiment_id}'."
            )
        started_dt = _parse_time(started_at)
        if started_dt is None:
            raise ValueError("started_at is required for run record attachment.")
        finished_dt = _parse_time(finished_at)
        run_key = _clean_text(source_run_id) or uuid.uuid4().hex[:12]
        record = RunRecord(
            record_id=f"{active.experiment_id}:{run_key}",
            source_run_id=run_key,
            source_tab=_clean_text(source_tab),
            source_module=_clean_text(source_module),
            run_type=_clean_text(run_type),
            status=_clean_text(status).upper() or "UNKNOWN",
            started_at=started_dt,
            finished_at=finished_dt,
            parameters=dict(parameters or {}),
            result_summary=dict(result_summary or {}),
            artifact_paths=tuple(
                str(item).strip() for item in (artifact_paths or []) if str(item).strip()
            ),
            experiment_context={
                "experiment_id": active.experiment_id,
                "title": active.title,
                "sample": active.sample,
                "operator": active.operator,
                "template_id": active.template_id,
                "cryostat": active.cryostat,
            },
        )
        payload = self._read_metadata_payload(active.experiment_id)
        existing_records = [
            RunRecord.from_payload(item) for item in payload.get("run_records", []) if isinstance(item, dict)
        ]
        updated_records: list[RunRecord] = []
        replaced = False
        for item in existing_records:
            if item.source_run_id == record.source_run_id and item.run_type == record.run_type:
                updated_records.append(record)
                replaced = True
            else:
                updated_records.append(item)
        if not replaced:
            updated_records.append(record)
        self._write_artifact(active, run_records=updated_records)
        return record

    def list_run_records(
        self,
        *,
        active_only: bool = False,
        experiment_id: str | None = None,
    ) -> list[RunRecord]:
        if active_only:
            if self._active is None:
                return []
            experiment_id = self._active.experiment_id
        if not experiment_id:
            return []
        payload = self._read_metadata_payload(experiment_id)
        records = [
            RunRecord.from_payload(item) for item in payload.get("run_records", []) if isinstance(item, dict)
        ]
        records.sort(key=lambda item: item.started_at, reverse=True)
        return records

    def create_experiment(
        self,
        name: str,
        operator: str,
        *,
        template_id: str = "custom",
        title: str | None = None,
        cryostat: str = "",
        sample: str = "",
        description: str = "",
        notes: str = "",
        custom_fields: dict[str, Any] | None = None,
        start_time: datetime | str | None = None,
    ) -> ExperimentInfo:
        self._require_experiment_mode()
        if self._active is not None:
            raise RuntimeError(
                f"Experiment '{self._active.name}' ({self._active.experiment_id}) is already active."
            )

        template = self.get_template(template_id)
        experiment_id = uuid.uuid4().hex[:12]
        now = _parse_time(start_time) or datetime.now(UTC)
        config_snapshot = self._read_config_snapshot()
        normalized_custom_fields = _normalize_custom_fields(custom_fields)

        info = ExperimentInfo(
            experiment_id=experiment_id,
            name=name,
            title=title or name,
            template_id=template.template_id,
            operator=operator,
            cryostat=cryostat,
            sample=sample,
            description=description,
            notes=notes,
            start_time=now,
            end_time=None,
            status=ExperimentStatus.RUNNING,
            config_snapshot=config_snapshot,
            custom_fields=normalized_custom_fields,
            report_enabled=template.report_enabled,
            sections=template.sections,
            artifact_dir=self._artifact_dir(experiment_id),
            metadata_path=self._metadata_path(experiment_id),
            retroactive=False,
        )

        self._write_start(info)
        self._write_artifact(info)
        self._set_active(info)
        return info

    def start_experiment(
        self,
        name: str,
        operator: str,
        *,
        template_id: str = "custom",
        title: str | None = None,
        cryostat: str = "",
        sample: str = "",
        description: str = "",
        notes: str = "",
        custom_fields: dict[str, Any] | None = None,
        start_time: datetime | str | None = None,
    ) -> str:
        info = self.create_experiment(
            name=name,
            operator=operator,
            template_id=template_id,
            title=title,
            cryostat=cryostat,
            sample=sample,
            description=description,
            notes=notes,
            custom_fields=custom_fields,
            start_time=start_time,
        )
        return info.experiment_id

    def get_active_experiment(self) -> ExperimentInfo | None:
        return self._active

    def update_experiment(
        self,
        experiment_id: str | None = None,
        *,
        title: str | None = None,
        sample: str | None = None,
        notes: str | None = None,
        description: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> ExperimentInfo:
        self._require_experiment_mode()
        active = self._require_active(experiment_id)
        updated = ExperimentInfo(
            experiment_id=active.experiment_id,
            name=active.name,
            title=title if title is not None else active.title,
            template_id=active.template_id,
            operator=active.operator,
            cryostat=active.cryostat,
            sample=sample if sample is not None else active.sample,
            description=description if description is not None else active.description,
            notes=notes if notes is not None else active.notes,
            start_time=active.start_time,
            end_time=None,
            status=ExperimentStatus.RUNNING,
            config_snapshot=active.config_snapshot,
            custom_fields={
                **active.custom_fields,
                **_normalize_custom_fields(custom_fields),
            },
            report_enabled=active.report_enabled,
            sections=active.sections,
            artifact_dir=active.artifact_dir,
            metadata_path=active.metadata_path,
            retroactive=active.retroactive,
        )
        self._write_end(updated)
        self._write_artifact(updated)
        self._set_active(updated)
        return updated

    def finalize_experiment(
        self,
        experiment_id: str | None = None,
        *,
        status: ExperimentStatus = ExperimentStatus.COMPLETED,
        title: str | None = None,
        sample: str | None = None,
        notes: str | None = None,
        description: str | None = None,
        custom_fields: dict[str, Any] | None = None,
        end_time: datetime | str | None = None,
    ) -> ExperimentInfo:
        self._require_experiment_mode()
        active = self._require_active(experiment_id)

        finished = ExperimentInfo(
            experiment_id=active.experiment_id,
            name=active.name,
            title=title or active.title,
            template_id=active.template_id,
            operator=active.operator,
            cryostat=active.cryostat,
            sample=sample if sample is not None else active.sample,
            description=description if description is not None else active.description,
            notes=notes if notes is not None else active.notes,
            start_time=active.start_time,
            end_time=_parse_time(end_time) or datetime.now(UTC),
            status=status,
            config_snapshot=active.config_snapshot,
            custom_fields={
                **active.custom_fields,
                **_normalize_custom_fields(custom_fields),
            },
            report_enabled=active.report_enabled,
            sections=active.sections,
            artifact_dir=active.artifact_dir,
            metadata_path=active.metadata_path,
            retroactive=active.retroactive,
        )

        run_records = self.list_run_records(experiment_id=finished.experiment_id)
        archive_snapshot = self._build_archive_snapshot(finished, run_records)
        self._write_end(finished)
        self._write_artifact(
            finished,
            run_records=archive_snapshot["run_records"],
            artifact_index=archive_snapshot["artifact_index"],
            result_tables=archive_snapshot["result_tables"],
            summary_metadata=archive_snapshot["summary_metadata"],
        )
        if finished.report_enabled:
            try:
                from cryodaq.reporting.generator import ReportGenerator

                ReportGenerator(self.data_dir).generate(finished.experiment_id)
            except Exception as exc:
                logger.warning("Failed to auto-generate reports for %s: %s", finished.experiment_id, exc)
        self._clear_active()
        return finished

    def stop_experiment(
        self,
        experiment_id: str | None = None,
        *,
        status: ExperimentStatus = ExperimentStatus.COMPLETED,
    ) -> None:
        self.finalize_experiment(experiment_id=experiment_id, status=status)

    def abort_experiment(
        self,
        experiment_id: str | None = None,
        *,
        title: str | None = None,
        sample: str | None = None,
        notes: str | None = None,
        description: str | None = None,
        custom_fields: dict[str, Any] | None = None,
        end_time: datetime | str | None = None,
    ) -> ExperimentInfo:
        return self.finalize_experiment(
            experiment_id=experiment_id,
            status=ExperimentStatus.ABORTED,
            title=title,
            sample=sample,
            notes=notes,
            description=description,
            custom_fields=custom_fields,
            end_time=end_time,
        )

    def create_retroactive_experiment(
        self,
        *,
        template_id: str,
        title: str,
        operator: str,
        start_time: datetime | str,
        end_time: datetime | str,
        sample: str = "",
        description: str = "",
        notes: str = "",
        cryostat: str = "",
        custom_fields: dict[str, Any] | None = None,
    ) -> ExperimentInfo:
        start_dt = _parse_time(start_time)
        end_dt = _parse_time(end_time)
        if start_dt is None or end_dt is None:
            raise ValueError("Retroactive experiment requires start_time and end_time.")
        if end_dt < start_dt:
            raise ValueError("Retroactive experiment end_time must be after start_time.")

        template = self.get_template(template_id)
        experiment_id = uuid.uuid4().hex[:12]
        info = ExperimentInfo(
            experiment_id=experiment_id,
            name=title,
            title=title,
            template_id=template.template_id,
            operator=operator,
            cryostat=cryostat,
            sample=sample,
            description=description,
            notes=notes,
            start_time=start_dt,
            end_time=end_dt,
            status=ExperimentStatus.COMPLETED,
            config_snapshot=self._read_config_snapshot(),
            custom_fields=_normalize_custom_fields(custom_fields),
            report_enabled=template.report_enabled,
            sections=template.sections,
            artifact_dir=self._artifact_dir(experiment_id),
            metadata_path=self._metadata_path(experiment_id),
            retroactive=True,
        )

        self._write_start(info)
        self._write_end(info)
        self._write_artifact(info)
        return info

    def _require_experiment_mode(self) -> None:
        if self.app_mode is not AppMode.EXPERIMENT:
            raise RuntimeError("Experiment lifecycle commands are only available in experiment mode.")

    def _require_active(self, experiment_id: str | None = None) -> ExperimentInfo:
        if self._active is None:
            raise RuntimeError("No active experiment to operate on.")
        if experiment_id is not None and experiment_id != self._active.experiment_id:
            raise ValueError(
                f"experiment_id '{experiment_id}' does not match active '{self._active.experiment_id}'."
            )
        return self._active

    def _normalize_app_mode(self, raw: AppMode | str) -> AppMode:
        if isinstance(raw, AppMode):
            return raw
        value = _clean_text(raw).lower()
        if not value:
            raise ValueError("app_mode is required.")
        return AppMode(value)

    def _set_active(self, info: ExperimentInfo) -> None:
        self._active = info
        self._state = ExperimentState(
            app_mode=self._state.app_mode,
            active_experiment_id=info.experiment_id,
        )
        self._write_state()

    def _clear_active(self) -> None:
        self._active = None
        self._state = ExperimentState(app_mode=self._state.app_mode, active_experiment_id=None)
        self._write_state()

    def _load_state(self) -> None:
        active_experiment_id: str | None = None
        app_mode = AppMode.EXPERIMENT
        if self._state_path.exists():
            try:
                payload = json.loads(self._state_path.read_text(encoding="utf-8"))
                app_mode = self._normalize_app_mode(payload.get("app_mode", AppMode.EXPERIMENT.value))
                active_experiment_id = _clean_text(payload.get("active_experiment_id")) or None
            except Exception as exc:
                logger.warning("Failed to load experiment state %s: %s", self._state_path, exc)
        self._state = ExperimentState(app_mode=app_mode, active_experiment_id=active_experiment_id)
        if active_experiment_id:
            active = self._read_experiment_from_metadata(active_experiment_id)
            if active is not None and active.status is ExperimentStatus.RUNNING:
                self._active = active
            else:
                self._clear_active()

    def _write_state(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            **self._state.to_payload(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        from cryodaq.core.atomic_write import atomic_write_text

        atomic_write_text(self._state_path, json.dumps(payload, ensure_ascii=False, indent=2))

    def _read_experiment_from_metadata(self, experiment_id: str) -> ExperimentInfo | None:
        metadata_path = self._metadata_path(experiment_id)
        if not metadata_path.exists():
            return None
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        experiment = payload.get("experiment", {})
        return ExperimentInfo(
            experiment_id=_clean_text(experiment.get("experiment_id")),
            name=_clean_text(experiment.get("name")),
            title=_clean_text(experiment.get("title") or experiment.get("name")),
            template_id=_clean_text(experiment.get("template_id")) or "custom",
            operator=_clean_text(experiment.get("operator")),
            cryostat=_clean_text(experiment.get("cryostat")),
            sample=_clean_text(experiment.get("sample")),
            description=_clean_text(experiment.get("description")),
            notes=_clean_text(experiment.get("notes")),
            start_time=_parse_time(experiment.get("start_time")) or datetime.now(UTC),
            end_time=_parse_time(experiment.get("end_time")),
            status=ExperimentStatus(_clean_text(experiment.get("status")) or ExperimentStatus.RUNNING.value),
            config_snapshot=dict(experiment.get("config_snapshot") or {}),
            custom_fields=_normalize_custom_fields(experiment.get("custom_fields")),
            report_enabled=bool(experiment.get("report_enabled", True)),
            sections=tuple(str(item) for item in experiment.get("sections", []) if str(item).strip()),
            artifact_dir=self._artifact_dir(experiment_id),
            metadata_path=metadata_path,
            retroactive=bool(experiment.get("retroactive", False)),
        )

    def _load_templates(self) -> dict[str, ExperimentTemplate]:
        templates_dir = self._templates_dir
        if templates_dir is None:
            return {"custom": ExperimentTemplate("custom", "Custom", ("setup", "notes"), True)}
        templates_dir.mkdir(parents=True, exist_ok=True)
        templates: dict[str, ExperimentTemplate] = {}
        for path in sorted(templates_dir.glob("*.yaml")):
            with path.open(encoding="utf-8") as handle:
                raw = yaml.safe_load(handle) or {}
            template_id = str(raw.get("id", "")).strip()
            if not template_id:
                raise ValueError(f"Experiment template {path} is missing 'id'.")
            name = str(raw.get("name", "")).strip()
            sections = tuple(str(item) for item in raw.get("sections", []) if str(item).strip())
            if not name or not sections:
                raise ValueError(f"Experiment template {path} is missing required fields.")
            custom_fields = tuple(
                TemplateField(
                    id=str(field.get("id", "")).strip(),
                    label=str(field.get("label", "")).strip(),
                    default=str(field.get("default", "")),
                )
                for field in raw.get("custom_fields", [])
                if str(field.get("id", "")).strip() and str(field.get("label", "")).strip()
            )
            templates[template_id] = ExperimentTemplate(
                template_id=template_id,
                name=name,
                sections=sections,
                report_enabled=bool(raw.get("report_enabled", True)),
                report_sections=tuple(
                    str(item) for item in raw.get("report_sections", []) if str(item).strip()
                ),
                custom_fields=custom_fields,
            )
        if "custom" not in templates:
            templates["custom"] = ExperimentTemplate(
                "custom",
                "Custom",
                ("setup", "notes"),
                True,
                ("title_page", "operator_log_section", "config_section"),
            )
        return templates

    def _artifact_dir(self, experiment_id: str) -> Path:
        return self._artifacts_dir / experiment_id

    def _metadata_path(self, experiment_id: str) -> Path:
        return self._artifact_dir(experiment_id) / "metadata.json"

    def _db_path_for_day(self, day: datetime) -> Path:
        return self._data_dir / f"data_{day.date().isoformat()}.db"

    def _all_db_names_for_range(self, start: datetime, end: datetime) -> set[str]:
        """Return all daily DB filenames that overlap [start, end]."""
        from datetime import timedelta
        names: set[str] = set()
        day = start.date()
        end_day = end.date()
        while day <= end_day:
            names.add(f"data_{day.isoformat()}.db")
            day += timedelta(days=1)
        return names

    def _db_path_for_today(self) -> Path:
        return self._db_path_for_day(datetime.now(UTC))

    def _get_connection(self, when: datetime | None = None) -> sqlite3.Connection:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        db_path = self._db_path_for_day(when or datetime.now(UTC))
        conn = sqlite3.connect(str(db_path), timeout=10)
        result = conn.execute("PRAGMA journal_mode=WAL;").fetchone()
        actual_mode = (result[0] if result else "").lower()
        if actual_mode != "wal":
            raise RuntimeError(
                f"SQLite WAL mode could not be enabled at {db_path}. "
                f"PRAGMA journal_mode returned {actual_mode!r}. "
                f"CryoDAQ requires WAL for cross-process read concurrency."
            )
        conn.execute(SCHEMA_EXPERIMENTS)
        conn.commit()
        return conn

    def _write_start(self, info: ExperimentInfo) -> None:
        conn = self._get_connection(info.start_time)
        try:
            conn.execute(
                "INSERT INTO experiments ("
                "experiment_id, name, operator, cryostat, sample, description, start_time, end_time, "
                "status, config_snapshot, template_id, title, notes, custom_fields, report_enabled, "
                "artifact_dir, metadata_path, sections, retroactive"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    info.experiment_id,
                    info.name,
                    info.operator,
                    info.cryostat,
                    info.sample,
                    info.description,
                    info.start_time.isoformat(),
                    info.end_time.isoformat() if info.end_time else None,
                    info.status.value,
                    json.dumps(info.config_snapshot, ensure_ascii=False),
                    info.template_id,
                    info.title,
                    info.notes,
                    json.dumps(info.custom_fields, ensure_ascii=False),
                    1 if info.report_enabled else 0,
                    str(info.artifact_dir or ""),
                    str(info.metadata_path or ""),
                    json.dumps(list(info.sections), ensure_ascii=False),
                    1 if info.retroactive else 0,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _write_end(self, info: ExperimentInfo) -> None:
        conn = self._get_connection(info.start_time)
        try:
            conn.execute(
                "UPDATE experiments SET "
                "name = ?, title = ?, sample = ?, description = ?, notes = ?, end_time = ?, status = ?, "
                "custom_fields = ?, report_enabled = ?, template_id = ?, artifact_dir = ?, metadata_path = ?, "
                "sections = ?, retroactive = ? "
                "WHERE experiment_id = ?;",
                (
                    info.name,
                    info.title,
                    info.sample,
                    info.description,
                    info.notes,
                    info.end_time.isoformat() if info.end_time else None,
                    info.status.value,
                    json.dumps(info.custom_fields, ensure_ascii=False),
                    1 if info.report_enabled else 0,
                    info.template_id,
                    str(info.artifact_dir or ""),
                    str(info.metadata_path or ""),
                    json.dumps(list(info.sections), ensure_ascii=False),
                    1 if info.retroactive else 0,
                    info.experiment_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _write_artifact(
        self,
        info: ExperimentInfo,
        *,
        run_records: list[RunRecord] | None = None,
        artifact_index: list[dict[str, Any]] | None = None,
        result_tables: list[dict[str, Any]] | None = None,
        summary_metadata: dict[str, Any] | None = None,
    ) -> None:
        artifact_dir = info.artifact_dir or self._artifact_dir(info.experiment_id)
        metadata_path = info.metadata_path or self._metadata_path(info.experiment_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        template = self.get_template(info.template_id)
        existing_payload = self._read_metadata_payload(info.experiment_id)
        payload = {
            **{key: value for key, value in existing_payload.items() if key not in {"experiment", "template", "data_range", "artifacts", "run_records"}},
            "schema_version": int(existing_payload.get("schema_version", 1) or 1),
            "experiment": info.to_payload(),
            "template": template.to_payload(),
            "data_range": {
                "start_time": info.start_time.isoformat(),
                "end_time": info.end_time.isoformat() if info.end_time else None,
                "daily_db_files": sorted(self._all_db_names_for_range(
                    info.start_time, info.end_time or info.start_time,
                )),
            },
            "artifacts": {
                "root_dir": str(artifact_dir),
                "metadata_path": str(metadata_path),
            },
            "run_records": [
                item.to_payload() if isinstance(item, RunRecord) else item
                for item in (
                    run_records
                    if run_records is not None
                    else [
                        RunRecord.from_payload(item)
                        for item in existing_payload.get("run_records", [])
                        if isinstance(item, dict)
                    ]
                )
            ],
            "artifact_index": [
                dict(item)
                for item in (
                    artifact_index
                    if artifact_index is not None
                    else list(existing_payload.get("artifact_index", []))
                )
            ],
            "result_tables": [
                dict(item)
                for item in (
                    result_tables
                    if result_tables is not None
                    else list(existing_payload.get("result_tables", []))
                )
            ],
            "summary_metadata": dict(
                summary_metadata
                if summary_metadata is not None
                else dict(existing_payload.get("summary_metadata") or {})
            ),
        }
        from cryodaq.core.atomic_write import atomic_write_text

        atomic_write_text(metadata_path, json.dumps(payload, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    # Phase tracking
    # ------------------------------------------------------------------

    def advance_phase(self, phase: str, operator: str = "") -> dict[str, Any]:
        """Transition to a new experiment phase. Closes the current phase."""
        if self._active is None:
            raise RuntimeError("No active experiment.")
        # Validate phase name
        try:
            ExperimentPhase(phase)
        except ValueError:
            valid = [p.value for p in ExperimentPhase]
            raise ValueError(f"Unknown phase '{phase}'. Valid: {valid}")

        now = datetime.now(UTC).isoformat()
        payload = self._read_metadata_payload(self._active.experiment_id)
        phases = payload.get("phases", [])

        # Close current phase
        if phases and phases[-1].get("ended_at") is None:
            phases[-1]["ended_at"] = now

        # Open new phase
        entry = {"phase": phase, "started_at": now, "ended_at": None, "operator": operator}
        phases.append(entry)

        payload["phases"] = phases
        payload["current_phase"] = phase
        metadata_path = self._metadata_path(self._active.experiment_id)
        from cryodaq.core.atomic_write import atomic_write_text

        atomic_write_text(metadata_path, json.dumps(payload, ensure_ascii=False, indent=2))

        return entry

    def get_current_phase(self) -> str | None:
        """Current phase of the active experiment, or None."""
        if self._active is None:
            return None
        payload = self._read_metadata_payload(self._active.experiment_id)
        return payload.get("current_phase")

    def get_phase_history(self) -> list[dict[str, Any]]:
        """Phase history of the active experiment."""
        if self._active is None:
            return []
        payload = self._read_metadata_payload(self._active.experiment_id)
        return payload.get("phases", [])

    def _read_metadata_payload(self, experiment_id: str) -> dict[str, Any]:
        metadata_path = self._metadata_path(experiment_id)
        if not metadata_path.exists():
            return {}
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    def _build_archive_snapshot(
        self,
        info: ExperimentInfo,
        run_records: list[RunRecord],
    ) -> dict[str, Any]:
        artifact_dir = info.artifact_dir or self._artifact_dir(info.experiment_id)
        archive_root = artifact_dir / "archive"
        plots_dir = archive_root / "plots"
        tables_dir = archive_root / "tables"
        summaries_dir = archive_root / "summaries"
        for path in (plots_dir, tables_dir, summaries_dir):
            path.mkdir(parents=True, exist_ok=True)

        readings = self._load_experiment_readings(info)
        artifact_index: list[dict[str, Any]] = []
        result_tables: list[dict[str, Any]] = []

        normalized_records, run_artifacts = self._materialize_run_record_artifacts(
            info,
            run_records,
            archive_root=archive_root,
        )
        artifact_index.extend(run_artifacts)

        measured_values_path = tables_dir / "measured_values.csv"
        self._write_measured_values_table(measured_values_path, readings)
        artifact_index.append(
            self._artifact_entry(
                category="table",
                role="measured_values",
                path=measured_values_path,
                summary={"rows": len(readings)},
            )
        )
        result_tables.append(
            {
                "table_id": "measured_values",
                "title": "Measured values",
                "path": str(measured_values_path),
                "row_count": len(readings),
            }
        )

        # Parquet archive (same readings, no re-scan from SQLite)
        from cryodaq.storage.parquet_archive import write_experiment_parquet
        parquet_path = tables_dir / "readings.parquet"
        parquet_result = write_experiment_parquet(readings, parquet_path)
        if parquet_result is not None:
            artifact_index.append(
                self._artifact_entry(
                    category="table",
                    role="experiment_data",
                    path=parquet_path,
                    summary={
                        "row_count": len(readings),
                        "format": "parquet",
                        "channels": sorted({r["channel"] for r in readings}),
                    },
                )
            )

        setpoint_values_path = tables_dir / "setpoint_values.csv"
        setpoint_rows = self._write_setpoint_values_table(setpoint_values_path, normalized_records)
        artifact_index.append(
            self._artifact_entry(
                category="table",
                role="setpoint_values",
                path=setpoint_values_path,
                summary={"rows": setpoint_rows},
            )
        )
        result_tables.append(
            {
                "table_id": "setpoint_values",
                "title": "Setpoint values",
                "path": str(setpoint_values_path),
                "row_count": setpoint_rows,
            }
        )

        run_results_path = tables_dir / "run_results.csv"
        run_result_rows = self._write_run_results_table(run_results_path, normalized_records)
        artifact_index.append(
            self._artifact_entry(
                category="table",
                role="run_results",
                path=run_results_path,
                summary={"rows": run_result_rows},
            )
        )
        result_tables.append(
            {
                "table_id": "run_results",
                "title": "Run results",
                "path": str(run_results_path),
                "row_count": run_result_rows,
            }
        )

        conductivity_rows = self._collect_conductivity_rows(normalized_records)
        if conductivity_rows:
            conductivity_table = tables_dir / "conductivity_vs_temperature.csv"
            self._write_conductivity_table(conductivity_table, conductivity_rows)
            artifact_index.append(
                self._artifact_entry(
                    category="table",
                    role="conductivity_vs_temperature",
                    path=conductivity_table,
                    summary={"rows": len(conductivity_rows)},
                )
            )
            result_tables.append(
                {
                    "table_id": "conductivity_vs_temperature",
                    "title": "Conductivity vs temperature",
                    "path": str(conductivity_table),
                    "row_count": len(conductivity_rows),
                }
            )
            conductivity_plot = plots_dir / "conductivity_vs_temperature.png"
            if self._write_xy_plot(
                conductivity_plot,
                conductivity_rows,
                title="Conductivity vs temperature",
                x_key="temperature_k",
                y_key="conductance_wk",
                x_label="Temperature (K)",
                y_label="Conductance (W/K)",
            ):
                artifact_index.append(
                    self._artifact_entry(
                        category="plot",
                        role="conductivity_vs_temperature",
                        path=conductivity_plot,
                        summary={"points": len(conductivity_rows)},
                    )
                )

        self._maybe_write_channel_plot(
            plots_dir / "temperature_overview.png",
            readings,
            artifact_index,
            channel_filter=lambda item: item["unit"] == "K",
            role="temperature_overview",
            title="Temperature overview",
            y_label="Temperature (K)",
        )
        self._maybe_write_channel_plot(
            plots_dir / "thermal_power.png",
            readings,
            artifact_index,
            channel_filter=lambda item: str(item["channel"]).endswith("/power"),
            role="thermal_power",
            title="Thermal power",
            y_label="Power",
        )
        self._maybe_write_channel_plot(
            plots_dir / "pressure.png",
            readings,
            artifact_index,
            channel_filter=lambda item: "pressure" in str(item["channel"]).lower()
            or str(item["unit"]).lower() in {"mbar", "pa"},
            role="pressure",
            title="Pressure",
            y_label="Pressure",
        )

        summary_metadata = {
            "experiment_id": info.experiment_id,
            "title": info.title,
            "sample": info.sample,
            "operator": info.operator,
            "status": info.status.value,
            "run_record_count": len(normalized_records),
            "artifact_count": len(artifact_index),
            "result_table_count": len(result_tables),
            "measured_value_rows": len(readings),
            "setpoint_rows": setpoint_rows,
            "run_result_rows": run_result_rows,
            "conductivity_rows": len(conductivity_rows),
        }
        summary_path = summaries_dir / "summary_metadata.json"
        from cryodaq.core.atomic_write import atomic_write_text

        atomic_write_text(summary_path, json.dumps(summary_metadata, ensure_ascii=False, indent=2))
        artifact_index.append(
            self._artifact_entry(
                category="summary",
                role="summary_metadata",
                path=summary_path,
                summary=summary_metadata,
            )
        )

        return {
            "run_records": normalized_records,
            "artifact_index": artifact_index,
            "result_tables": result_tables,
            "summary_metadata": summary_metadata,
        }

    def _load_experiment_readings(self, info: ExperimentInfo) -> list[dict[str, Any]]:
        if info.end_time is None:
            return []
        rows: list[dict[str, Any]] = []
        day = info.start_time.date()
        end_day = info.end_time.date()
        while day <= end_day:
            db_path = self._data_dir / f"data_{day.isoformat()}.db"
            if db_path.exists():
                conn = sqlite3.connect(str(db_path), timeout=10)
                conn.row_factory = sqlite3.Row
                try:
                    query = (
                        "SELECT timestamp, instrument_id, channel, value, unit, status "
                        "FROM readings WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp"
                    )
                    params = (info.start_time.timestamp(), info.end_time.timestamp())
                    for row in conn.execute(query, params).fetchall():
                        rows.append(
                            {
                                "timestamp": datetime.fromtimestamp(float(row["timestamp"]), tz=UTC),
                                "instrument_id": str(row["instrument_id"] or ""),
                                "channel": str(row["channel"] or ""),
                                "value": float(row["value"]),
                                "unit": str(row["unit"] or ""),
                                "status": str(row["status"] or ""),
                            }
                        )
                except sqlite3.OperationalError:
                    logger.info("readings table not found in %s", db_path.name)
                finally:
                    conn.close()
            day = day.fromordinal(day.toordinal() + 1)
        return rows

    def _materialize_run_record_artifacts(
        self,
        info: ExperimentInfo,
        run_records: list[RunRecord],
        *,
        archive_root: Path,
    ) -> tuple[list[RunRecord], list[dict[str, Any]]]:
        normalized_records: list[RunRecord] = []
        artifact_index: list[dict[str, Any]] = []
        for record in run_records:
            normalized_paths: list[str] = []
            for raw_path in record.artifact_paths:
                source = Path(str(raw_path))
                if not source.exists():
                    continue
                if str(source).startswith(str(info.artifact_dir or "")):
                    target = source
                    linked = False
                else:
                    target_dir = archive_root / "runs" / self._safe_slug(record.source_tab) / self._safe_slug(record.source_run_id)
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / source.name
                    if not target.exists():
                        try:
                            os.link(str(source), str(target))
                            linked = True
                        except OSError:
                            shutil.copy2(source, target)
                            linked = False
                    else:
                        linked = target.stat().st_size == source.stat().st_size
                normalized_paths.append(str(target))
                artifact_index.append(
                    self._artifact_entry(
                        category="run_artifact",
                        role=record.run_type,
                        path=target,
                        summary={
                            "run_record_id": record.record_id,
                            "source_path": str(source),
                            "materialized": str(target),
                            "linked": linked,
                        },
                    )
                )
            normalized_records.append(
                RunRecord(
                    record_id=record.record_id,
                    source_run_id=record.source_run_id,
                    source_tab=record.source_tab,
                    source_module=record.source_module,
                    run_type=record.run_type,
                    status=record.status,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                    parameters=record.parameters,
                    result_summary=record.result_summary,
                    artifact_paths=tuple(normalized_paths),
                    experiment_context=record.experiment_context,
                )
            )
        return normalized_records, artifact_index

    def _write_measured_values_table(self, path: Path, readings: list[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["timestamp", "instrument_id", "channel", "value", "unit", "status"])
            for item in readings:
                writer.writerow(
                    [
                        item["timestamp"].isoformat(),
                        item["instrument_id"],
                        item["channel"],
                        item["value"],
                        item["unit"],
                        item["status"],
                    ]
                )

    def _write_setpoint_values_table(self, path: Path, run_records: list[RunRecord]) -> int:
        rows = 0
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["run_record_id", "source_tab", "run_type", "parameter", "value"])
            for record in run_records:
                for key, value in sorted(record.parameters.items()):
                    writer.writerow([record.record_id, record.source_tab, record.run_type, key, json.dumps(value, ensure_ascii=False)])
                    rows += 1
        return rows

    def _write_run_results_table(self, path: Path, run_records: list[RunRecord]) -> int:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "run_record_id",
                    "source_tab",
                    "source_module",
                    "run_type",
                    "status",
                    "started_at",
                    "finished_at",
                    "artifact_count",
                    "result_summary_json",
                ]
            )
            for record in run_records:
                writer.writerow(
                    [
                        record.record_id,
                        record.source_tab,
                        record.source_module,
                        record.run_type,
                        record.status,
                        record.started_at.isoformat(),
                        record.finished_at.isoformat() if record.finished_at else "",
                        len(record.artifact_paths),
                        json.dumps(record.result_summary, ensure_ascii=False),
                    ]
                )
        return len(run_records)

    def _collect_conductivity_rows(self, run_records: list[RunRecord]) -> list[dict[str, float]]:
        rows: list[dict[str, float]] = []
        for record in run_records:
            if record.run_type != "autosweep":
                continue
            for artifact_path in record.artifact_paths:
                path = Path(artifact_path)
                if path.suffix.lower() != ".csv" or not path.exists():
                    continue
                try:
                    with path.open(encoding="utf-8", newline="") as handle:
                        reader = csv.DictReader(
                            line for line in handle if not line.startswith("#")
                        )
                        for item in reader:
                            try:
                                rows.append(
                                    {
                                        "temperature_k": float(item.get("T_avg_K", "")),
                                        "conductance_wk": float(item.get("G_WK", "")),
                                        "resistance_kw": float(item.get("R_KW", "")),
                                    }
                                )
                            except (TypeError, ValueError):
                                continue
                except Exception as exc:
                    logger.warning("Failed to parse autosweep artifact %s: %s", path, exc)
        return rows

    def _write_conductivity_table(self, path: Path, rows: list[dict[str, float]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["temperature_k", "conductance_wk", "resistance_kw"])
            for item in rows:
                writer.writerow([item["temperature_k"], item["conductance_wk"], item["resistance_kw"]])

    def _maybe_write_channel_plot(
        self,
        path: Path,
        readings: list[dict[str, Any]],
        artifact_index: list[dict[str, Any]],
        *,
        channel_filter: Any,
        role: str,
        title: str,
        y_label: str,
    ) -> None:
        filtered = [item for item in readings if channel_filter(item)]
        if not filtered:
            return
        if self._write_channel_plot(path, filtered, title=title, y_label=y_label):
            artifact_index.append(
                self._artifact_entry(
                    category="plot",
                    role=role,
                    path=path,
                    summary={"points": len(filtered)},
                )
            )

    def _write_channel_plot(
        self,
        path: Path,
        readings: list[dict[str, Any]],
        *,
        title: str,
        y_label: str,
    ) -> bool:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            plt.figure(figsize=(8, 3.5))
            series: dict[str, list[tuple[datetime, float]]] = {}
            for item in readings:
                series.setdefault(str(item["channel"]), []).append((item["timestamp"], float(item["value"])))
            for channel, values in sorted(series.items()):
                plt.plot([stamp for stamp, _ in values], [value for _, value in values], label=channel)
            plt.title(title)
            plt.ylabel(y_label)
            if len(series) <= 6:
                plt.legend(fontsize=6)
            plt.tight_layout()
            plt.savefig(path, dpi=150, bbox_inches="tight")
            plt.close()
            return True
        except Exception as exc:
            logger.warning("Failed to generate archive plot %s: %s", path, exc)
            return False

    def _write_xy_plot(
        self,
        path: Path,
        rows: list[dict[str, float]],
        *,
        title: str,
        x_key: str,
        y_key: str,
        x_label: str,
        y_label: str,
    ) -> bool:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            plt.figure(figsize=(6, 4))
            plt.plot([item[x_key] for item in rows], [item[y_key] for item in rows], marker="o")
            plt.title(title)
            plt.xlabel(x_label)
            plt.ylabel(y_label)
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(path, dpi=150, bbox_inches="tight")
            plt.close()
            return True
        except Exception as exc:
            logger.warning("Failed to generate archive XY plot %s: %s", path, exc)
            return False

    @staticmethod
    def _artifact_entry(
        *,
        category: str,
        role: str,
        path: Path,
        summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "artifact_id": f"{category}:{role}:{path.name}",
            "category": category,
            "role": role,
            "path": str(path),
            "summary": dict(summary or {}),
        }

    @staticmethod
    def _safe_slug(raw: str) -> str:
        text = _clean_text(raw) or "item"
        return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)

    def _read_config_snapshot(self) -> dict[str, Any]:
        if not self._instruments_config.exists():
            logger.warning("Instrument config not found: %s", self._instruments_config)
            return {}
        try:
            with self._instruments_config.open(encoding="utf-8") as handle:
                return yaml.safe_load(handle) or {}
        except Exception as exc:
            logger.error("Failed to read instruments config: %s", exc)
            return {}
