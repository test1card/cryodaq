"""Experiment templates, lifecycle metadata, and artifact persistence."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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
        }


def _parse_time(raw: datetime | str | None) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw.astimezone(timezone.utc)
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
        self._active: ExperimentInfo | None = None
        self._templates_cache: dict[str, ExperimentTemplate] | None = None

    @property
    def active_experiment(self) -> ExperimentInfo | None:
        return self._active

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
            "active_experiment": self._active.to_payload() if self._active else None,
            "templates": [template.to_payload() for template in self.get_templates()],
        }

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
        entries: list[ArchiveEntry] = []
        if not self._artifacts_dir.exists():
            return entries

        for metadata_path in sorted(self._artifacts_dir.glob("*/metadata.json")):
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                experiment = payload.get("experiment", {})
                template = payload.get("template", {})
                artifact_dir = metadata_path.parent
                docx_path = artifact_dir / "reports" / "report.docx"
                pdf_path = artifact_dir / "reports" / "report.pdf"
                entry = ArchiveEntry(
                    experiment_id=_clean_text(experiment.get("experiment_id")),
                    title=_clean_text(experiment.get("title") or experiment.get("name")),
                    template_id=_clean_text(experiment.get("template_id") or template.get("id")),
                    template_name=_clean_text(template.get("name") or experiment.get("template_id")),
                    operator=_clean_text(experiment.get("operator")),
                    sample=_clean_text(experiment.get("sample")),
                    status=_clean_text(experiment.get("status")),
                    start_time=_parse_time(experiment.get("start_time")) or datetime.now(timezone.utc),
                    end_time=_parse_time(experiment.get("end_time")),
                    artifact_dir=artifact_dir,
                    metadata_path=metadata_path,
                    docx_path=docx_path if docx_path.exists() else None,
                    pdf_path=pdf_path if pdf_path.exists() else None,
                    report_enabled=bool(experiment.get("report_enabled", True)),
                    report_present=docx_path.exists() or pdf_path.exists(),
                    notes=_clean_text(experiment.get("notes")),
                    retroactive=bool(experiment.get("retroactive", False)),
                )
            except Exception as exc:
                logger.warning("Failed to load archive metadata %s: %s", metadata_path, exc)
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
        if self._active is not None:
            raise RuntimeError(
                f"Experiment '{self._active.name}' ({self._active.experiment_id}) is already active."
            )

        template = self.get_template(template_id)
        experiment_id = uuid.uuid4().hex[:12]
        now = _parse_time(start_time) or datetime.now(timezone.utc)
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
        self._active = info
        return experiment_id

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
        if self._active is None:
            raise RuntimeError("No active experiment to finalize.")
        if experiment_id is not None and experiment_id != self._active.experiment_id:
            raise ValueError(
                f"experiment_id '{experiment_id}' does not match active '{self._active.experiment_id}'."
            )

        finished = ExperimentInfo(
            experiment_id=self._active.experiment_id,
            name=self._active.name,
            title=title or self._active.title,
            template_id=self._active.template_id,
            operator=self._active.operator,
            cryostat=self._active.cryostat,
            sample=sample if sample is not None else self._active.sample,
            description=description if description is not None else self._active.description,
            notes=notes if notes is not None else self._active.notes,
            start_time=self._active.start_time,
            end_time=_parse_time(end_time) or datetime.now(timezone.utc),
            status=status,
            config_snapshot=self._active.config_snapshot,
            custom_fields={
                **self._active.custom_fields,
                **_normalize_custom_fields(custom_fields),
            },
            report_enabled=self._active.report_enabled,
            sections=self._active.sections,
            artifact_dir=self._active.artifact_dir,
            metadata_path=self._active.metadata_path,
            retroactive=self._active.retroactive,
        )

        self._write_end(finished)
        self._write_artifact(finished)
        self._active = None
        return finished

    def stop_experiment(
        self,
        experiment_id: str | None = None,
        *,
        status: ExperimentStatus = ExperimentStatus.COMPLETED,
    ) -> None:
        self.finalize_experiment(experiment_id=experiment_id, status=status)

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

    def _db_path_for_today(self) -> Path:
        return self._db_path_for_day(datetime.now(timezone.utc))

    def _get_connection(self, when: datetime | None = None) -> sqlite3.Connection:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        db_path = self._db_path_for_day(when or datetime.now(timezone.utc))
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL;")
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

    def _write_artifact(self, info: ExperimentInfo) -> None:
        artifact_dir = info.artifact_dir or self._artifact_dir(info.experiment_id)
        metadata_path = info.metadata_path or self._metadata_path(info.experiment_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        template = self.get_template(info.template_id)
        payload = {
            "schema_version": 1,
            "experiment": info.to_payload(),
            "template": template.to_payload(),
            "data_range": {
                "start_time": info.start_time.isoformat(),
                "end_time": info.end_time.isoformat() if info.end_time else None,
                "daily_db_files": sorted(
                    {
                        self._db_path_for_day(info.start_time).name,
                        self._db_path_for_day(info.end_time or info.start_time).name,
                    }
                ),
            },
            "artifacts": {
                "root_dir": str(artifact_dir),
                "metadata_path": str(metadata_path),
            },
        }
        metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

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
