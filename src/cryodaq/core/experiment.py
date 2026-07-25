"""Experiment templates, lifecycle metadata, and artifact persistence."""

from __future__ import annotations

import csv
import functools
import hashlib
import json
import logging
import math
import os
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any

import yaml

from cryodaq.report_state import (
    ReportContractError,
    load_current_manifest,
    load_report_state,
    report_force_context,
    resolve_report_artifact,
    resolve_report_paths,
)
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.archive_reader import ArchiveReader

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

SCHEMA_SINGLE_RUNNING_EXPERIMENT = """
CREATE UNIQUE INDEX IF NOT EXISTS ux_experiments_single_running
ON experiments(status) WHERE status = 'RUNNING';
"""

_LIFECYCLE_LOCKS_GUARD = threading.Lock()
_LIFECYCLE_LOCKS: dict[str, threading.RLock] = {}

_TRANSITION_SCHEMA_VERSION = 2
_STATE_SCHEMA_VERSION = 2
_HEX_ID_LENGTH = 32
_SHA256_LENGTH = 64
_UNSET = object()


def _lifecycle_lock_for(data_dir: Path) -> threading.RLock:
    key = os.path.normcase(str(data_dir.resolve()))
    with _LIFECYCLE_LOCKS_GUARD:
        return _LIFECYCLE_LOCKS.setdefault(key, threading.RLock())


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_lower_hex(value: Any, length: int) -> bool:
    return (
        type(value) is str
        and len(value) == length
        and value == value.lower()
        and all(char in "0123456789abcdef" for char in value)
    )


def _serialized_lifecycle(method):
    """Serialize every mutation for one experiment data root."""

    @functools.wraps(method)
    def guarded(self, *args, **kwargs):
        with self._lifecycle_lock:
            self._recover_transition()
            return method(self, *args, **kwargs)

    return guarded


class ExperimentStatus(Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class ExperimentPhase(StrEnum):
    PREPARATION = "preparation"
    VACUUM = "vacuum"
    COOLDOWN = "cooldown"
    MEASUREMENT = "measurement"
    WARMUP = "warmup"
    TEARDOWN = "teardown"


class ExperimentIdentityMismatchError(RuntimeError):
    """A command was submitted for a different experiment generation."""


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
    report_authority: str
    report_generation_id: str | None
    report_state_status: str | None
    report_attempt_count: int | None
    report_max_attempts: int | None
    report_error_code: str | None
    report_error_text: str
    report_force_required: bool
    report_force_context: str | None
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
            "report_authority": self.report_authority,
            "report_generation_id": self.report_generation_id,
            "report_state_status": self.report_state_status,
            "report_attempt_count": self.report_attempt_count,
            "report_max_attempts": self.report_max_attempts,
            "report_error_code": self.report_error_code,
            "report_error_text": self.report_error_text,
            "report_force_required": self.report_force_required,
            "report_force_context": self.report_force_context,
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
class OperatorExperimentSnapshot:
    """Constant-time, path-free experiment identity cut for operator views.

    This is deliberately not a recording receipt. The experiment manager
    owns card/lifecycle identity, but it does not own a durable recording
    session. Consumers must therefore keep recording truth UNKNOWN until a
    separately reviewed recording authority exists.
    """

    revision: int
    experiment_id: str | None
    experiment_name: str | None
    phase: str | None


@dataclass(frozen=True, slots=True)
class ExperimentReadingsSnapshot:
    rows: tuple[dict[str, Any], ...]
    complete: bool
    truncated: bool
    issues: tuple[str, ...]


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
        record_id = _clean_text(payload.get("record_id"))
        source_run_id = _clean_text(payload.get("source_run_id"))
        started_at = _parse_time(payload.get("started_at"))
        finished_at = _parse_time(payload.get("finished_at"))
        if not record_id or not source_run_id or started_at is None:
            raise ValueError("Run record identity and started_at must be explicit.")
        if finished_at is not None and finished_at < started_at:
            raise ValueError("Run record finished_at cannot precede started_at.")
        return cls(
            record_id=record_id,
            source_run_id=source_run_id,
            source_tab=_clean_text(payload.get("source_tab")),
            source_module=_clean_text(payload.get("source_module")),
            run_type=_clean_text(payload.get("run_type")),
            status=_clean_text(payload.get("status")) or "UNKNOWN",
            started_at=started_at,
            finished_at=finished_at,
            parameters=dict(payload.get("parameters") or {}),
            result_summary=dict(payload.get("result_summary") or {}),
            artifact_paths=tuple(str(item).strip() for item in payload.get("artifact_paths", []) if str(item).strip()),
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


def _report_error_display(error_code: Any, error_text: Any) -> str:
    """Project report failures without leaking raw paths or exception payloads."""
    if not str(error_text or "").strip():
        return ""
    code = str(error_code or "report_failed")[:128]
    code = "".join(char for char in code if 32 <= ord(char) < 127).strip()
    return f"Previous report attempt failed ({code or 'report_failed'})."[:512]


def _serialized_lifecycle_mutation(method: Any) -> Any:
    """Hold lifecycle recovery and mutation admission through side effects."""

    @functools.wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self._lifecycle_lock:
            self._recover_transition()
            with self._mutation_lock:
                self._assert_mutation_available()
                return method(self, *args, **kwargs)

    return wrapped


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
        self._transition_path = self._data_dir / "experiment_transition.json"
        self._lifecycle_lock = _lifecycle_lock_for(self._data_dir)
        self._active: ExperimentInfo | None = None
        self._state = ExperimentState(app_mode=AppMode.EXPERIMENT)
        self._operator_phase: str | None = None
        self._operator_snapshot = OperatorExperimentSnapshot(0, None, None, None)
        self._mutation_lock = threading.RLock()
        self._durable_mutation_id: str | None = None
        self._manager_incarnation = uuid.uuid4().hex
        self._state_revision = 0
        self._last_transition_receipt: dict[str, Any] | None = None
        self._templates_cache: dict[str, ExperimentTemplate] | None = None
        with self._lifecycle_lock:
            self._load_state_authority()
            self._recover_transition()
            self._load_state()
        if self._active is not None:
            self._operator_phase = self.get_current_phase()
        self._refresh_operator_snapshot(force=True)

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

    def snapshot_operator_experiment(self) -> OperatorExperimentSnapshot:
        """Return one immutable, no-I/O experiment identity cut.

        Sampling performs no filesystem work and exposes no mutable metadata,
        paths, operator identity, command method, or recording capability.
        """

        return self._operator_snapshot

    @contextmanager
    def experiment_cas(self, expected_experiment_id: str) -> Iterator[str]:
        """Reserve an experiment identity across an asynchronous durable mutation.

        The reservation is deliberately not held as a native thread lock while
        the caller awaits its writer.  Other lifecycle callers can therefore
        keep the event loop live, but they observe the reservation and fail
        closed.  The owner must call :meth:`assert_experiment_cas` immediately
        before its durable write; exit revalidates the identity once more.
        """
        if type(expected_experiment_id) is not str or not expected_experiment_id:
            raise RuntimeError("Experiment identity is required.")
        with self._mutation_lock:
            if self._active is None or self._active.experiment_id != expected_experiment_id:
                raise RuntimeError("Experiment identity mismatch.")
            if self._durable_mutation_id is not None:
                raise RuntimeError("A durable experiment mutation is already in progress.")
            self._durable_mutation_id = expected_experiment_id
        try:
            yield expected_experiment_id
            self.assert_experiment_cas(expected_experiment_id)
        finally:
            with self._mutation_lock:
                if self._durable_mutation_id == expected_experiment_id:
                    self._durable_mutation_id = None

    def assert_experiment_cas(self, expected_experiment_id: str) -> None:
        """Revalidate the reserved identity immediately before durable I/O."""
        with self._mutation_lock:
            if self._durable_mutation_id != expected_experiment_id:
                raise RuntimeError("Experiment mutation reservation is not owned by this caller.")
            if self._active is None or self._active.experiment_id != expected_experiment_id:
                raise RuntimeError("Experiment identity changed during mutation.")

    def _assert_mutation_available(self) -> None:
        with self._mutation_lock:
            if self._durable_mutation_id is not None:
                raise RuntimeError("A durable experiment mutation is in progress.")

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
        phase_started_at = self._get_phase_started_at()
        return {
            "ok": True,
            "app_mode": self.app_mode.value,
            "active_experiment": self._active.to_payload() if self._active else None,
            "current_phase": self.get_current_phase(),
            "phase_started_at": phase_started_at,
            "phases": self.get_phase_history(),
            "run_records": [record.to_payload() for record in self.list_run_records(active_only=True)],
            "templates": [template.to_payload() for template in self.get_templates()],
        }

    def _get_phase_started_at(self) -> float | None:
        """Unix timestamp of when the current phase started, or None."""
        history = self.get_phase_history()
        if not history:
            return None
        last = history[-1]
        if last.get("ended_at") is not None:
            return None
        started = last.get("started_at")
        if started is None:
            return None
        if isinstance(started, str):
            return datetime.fromisoformat(started).timestamp()
        return float(started)

    def get_app_mode(self) -> AppMode:
        return self.app_mode

    @_serialized_lifecycle_mutation
    def set_app_mode(self, mode: AppMode | str) -> AppMode:
        next_mode = self._normalize_app_mode(mode)
        if next_mode is AppMode.DEBUG and self._active is not None:
            raise RuntimeError("Нельзя переключиться в режим отладки, пока карточка эксперимента активна.")
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
        data_root = self._data_dir.resolve()
        if self._artifacts_dir.is_symlink():
            logger.warning("Ignoring symlinked experiments archive root: %s", self._artifacts_dir)
            return entries
        resolved_artifacts = self._artifacts_dir.resolve()
        if resolved_artifacts != data_root and data_root not in resolved_artifacts.parents:
            logger.warning("Ignoring experiments archive root outside data directory")
            return entries
        if not self._artifacts_dir.exists():
            return entries

        for metadata_path in sorted(self._artifacts_dir.glob("*/metadata.json")):
            try:
                archive_root = self._artifacts_dir.resolve()
                resolved_metadata = metadata_path.resolve()
                if (
                    metadata_path.is_symlink()
                    or metadata_path.parent.is_symlink()
                    or archive_root not in resolved_metadata.parents
                ):
                    raise ValueError("archive metadata escapes experiments root")
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                experiment = payload.get("experiment", {})
                template = payload.get("template", {})
                run_records = tuple(dict(item) for item in payload.get("run_records", []) if isinstance(item, dict))
                artifact_index = tuple(
                    dict(item) for item in payload.get("artifact_index", []) if isinstance(item, dict)
                )
                result_tables = tuple(dict(item) for item in payload.get("result_tables", []) if isinstance(item, dict))
                artifact_dir = metadata_path.parent
                manifest = None
                report_paths = None
                report_authority = "none"
                report_generation_id = None
                pointer = artifact_dir / "reports" / "current_report.json"
                pointer_present = os.path.lexists(pointer)
                try:
                    report_paths = resolve_report_paths(artifact_dir)
                    manifest = load_current_manifest(artifact_dir)
                except (OSError, ReportContractError) as exc:
                    logger.warning("Ignoring unsafe report manifest %s: %s", artifact_dir, exc)
                    if pointer_present:
                        report_authority = "invalid"
                if pointer_present and manifest is None:
                    # The pointer may have disappeared between lexists() and
                    # the validated read.  Preserve the observed manifest
                    # authority instead of reclassifying the entry as a
                    # legacy/no-report archive during that race.
                    report_authority = "invalid"
                if manifest is not None:
                    report_authority = "manifest"
                    report_generation_id = manifest["generation_id"]
                    report = manifest["report"]
                    manifest_docx = artifact_dir / report["docx_path"]
                    docx_path = manifest_docx if manifest_docx.is_file() else None
                    pdf_path = artifact_dir / report["pdf_path"] if report["pdf_path"] is not None else None
                elif not pointer_present and report_paths is not None:
                    docx_path = None
                    pdf_path = None
                    for name in ("report_editable.docx", "report.docx"):
                        try:
                            candidate = resolve_report_artifact(
                                report_paths.reports / name,
                                report_paths,
                                field="archive DOCX",
                                required=False,
                            )
                            if candidate.exists():
                                docx_path = resolve_report_artifact(
                                    report_paths.reports / name,
                                    report_paths,
                                    field="archive DOCX",
                                    required=True,
                                )
                                break
                        except ReportContractError as exc:
                            logger.warning("Ignoring unsafe archive DOCX: %s", exc)
                    for name in ("report_raw.pdf", "report.pdf"):
                        try:
                            candidate = resolve_report_artifact(
                                report_paths.reports / name,
                                report_paths,
                                field="archive PDF",
                                required=False,
                            )
                            if candidate.exists():
                                pdf_path = resolve_report_artifact(
                                    report_paths.reports / name,
                                    report_paths,
                                    field="archive PDF",
                                    required=True,
                                )
                                break
                        except ReportContractError as exc:
                            logger.warning("Ignoring unsafe archive PDF: %s", exc)
                    if docx_path is not None or pdf_path is not None:
                        report_authority = "legacy"
                else:
                    docx_path = None
                    pdf_path = None

                state = None
                report_state_status = None
                try:
                    state = load_report_state(artifact_dir)
                except (OSError, ReportContractError) as exc:
                    logger.warning("Ignoring invalid report state %s: %s", artifact_dir, exc)
                    report_state_status = "INVALID"
                if state is not None:
                    report_state_status = state["status"]
                report_force_required = bool(
                    state is not None
                    and state["status"] in {"FAILED", "RUNNING"}
                    and int(state["attempt_count"]) >= int(state["max_attempts"])
                    and report_authority != "invalid"
                )
                force_context = (
                    report_force_context(state, manifest) if report_force_required and state is not None else None
                )
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
                    docx_path=docx_path if docx_path is not None and docx_path.exists() else None,
                    pdf_path=pdf_path if pdf_path is not None and pdf_path.exists() else None,
                    report_enabled=bool(experiment.get("report_enabled", True)),
                    report_present=(docx_path is not None and docx_path.exists())
                    or (pdf_path is not None and pdf_path.exists()),
                    report_authority=report_authority,
                    report_generation_id=report_generation_id,
                    report_state_status=report_state_status,
                    report_attempt_count=(int(state["attempt_count"]) if state is not None else None),
                    report_max_attempts=(int(state["max_attempts"]) if state is not None else None),
                    report_error_code=(
                        str(state["error_code"])[:128]
                        if state is not None and state["error_code"] is not None
                        else None
                    ),
                    report_error_text=(
                        _report_error_display(state["error_code"], state["error_text"]) if state is not None else ""
                    ),
                    report_force_required=report_force_required,
                    report_force_context=force_context,
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

    @_serialized_lifecycle_mutation
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
            raise ValueError(f"experiment_id '{experiment_id}' does not match active '{active.experiment_id}'.")
        started_dt = _parse_time(started_at)
        if started_dt is None:
            raise ValueError("started_at is required for run record attachment.")
        finished_dt = _parse_time(finished_at)
        if finished_dt is not None and finished_dt < started_dt:
            raise ValueError("finished_at cannot precede started_at.")
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
            artifact_paths=tuple(str(item).strip() for item in (artifact_paths or []) if str(item).strip()),
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
        records = [RunRecord.from_payload(item) for item in payload.get("run_records", []) if isinstance(item, dict)]
        records.sort(key=lambda item: item.started_at, reverse=True)
        return records

    @_serialized_lifecycle_mutation
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
        report_enabled: bool | None = None,
    ) -> ExperimentInfo:
        self._assert_mutation_available()
        self._require_experiment_mode()
        if self._active is not None:
            raise RuntimeError(
                f"Experiment '{self._active.name}' ({self._active.experiment_id}) is already active."  # noqa: E501
            )
        persisted_running = self._persisted_running_experiment_ids()
        if persisted_running:
            raise RuntimeError("A persisted RUNNING experiment already exists: " + ", ".join(sorted(persisted_running)))

        template = self.get_template(template_id)
        experiment_id = uuid.uuid4().hex[:12]
        now = _parse_time(start_time) or datetime.now(UTC)
        config_snapshot = self._read_config_snapshot()
        normalized_custom_fields = _normalize_custom_fields(custom_fields)

        # IV.4 F6: per-experiment report_enabled override. The new
        # NewExperimentDialog checkbox passes this through so operators
        # can turn off the auto-report for a one-off run without
        # editing the template YAML. None (default) keeps the
        # template's configured value.
        effective_report_enabled = template.report_enabled if report_enabled is None else bool(report_enabled)

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
            report_enabled=effective_report_enabled,
            sections=template.sections,
            artifact_dir=self._artifact_dir(experiment_id),
            metadata_path=self._metadata_path(experiment_id),
            retroactive=False,
        )

        self._commit_transition("create", info)
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

    @_serialized_lifecycle_mutation
    def attach_composition_photo(
        self,
        experiment_id: str,
        photo_bytes: bytes,
        *,
        caption: str = "",
        operator_username: str = "",
        file_id: str = "",
        channels_mentioned: list[str] | None = None,
        mime_type: str = "image/jpeg",
    ) -> dict[str, Any]:
        """Persist composition photo to experiment artifact dir.

        Writes photo file + JSON sidecar atomically. Appends artifact_index entry
        to metadata.json. Returns dict with filename, path, metadata.
        """
        artifact_dir = self._artifact_dir(experiment_id)
        if not artifact_dir.exists():
            raise ValueError(f"Experiment artifact dir not found: {artifact_dir}")

        composition_dir = artifact_dir / "composition"
        composition_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(UTC)
        ts_str = now.strftime("%Y%m%dT%H%M%S")
        ext = "jpg" if "jpeg" in mime_type.lower() else "png"
        existing = list(composition_dir.glob("*.jpg")) + list(composition_dir.glob("*.png"))
        seq = len(existing) + 1
        filename = f"{ts_str}_{seq:03d}.{ext}"
        photo_path = composition_dir / filename
        sidecar_path = composition_dir / f"{ts_str}_{seq:03d}.json"

        dimensions = _validate_photo_dimensions(photo_bytes)
        if dimensions is None:
            raise ValueError("Invalid or unreadable photo data")

        from cryodaq.core.atomic_write import atomic_write_bytes, atomic_write_text

        atomic_write_bytes(photo_path, photo_bytes)

        # Phase at upload time (only available for active experiment)
        phase_at_upload: str | None = None
        exp_title = ""
        if self._active and self._active.experiment_id == experiment_id:
            try:
                phase_at_upload = self.get_current_phase()
            except Exception:
                pass
            exp_title = self._active.title or self._active.name

        sidecar_meta: dict[str, Any] = {
            "filename": filename,
            "telegram_file_id": file_id,
            "telegram_username": operator_username,
            "caption": caption[:500] if caption else "",
            "uploaded_at": now.isoformat(),
            "file_size_bytes": len(photo_bytes),
            "dimensions": dimensions,
            "mime_type": mime_type,
            "experiment_id": experiment_id,
            "experiment_title": exp_title,
            "phase_at_upload": phase_at_upload,
            "channels_mentioned": list(channels_mentioned or []),
        }
        atomic_write_text(sidecar_path, json.dumps(sidecar_meta, ensure_ascii=False, indent=2))

        artifact_entry: dict[str, Any] = {
            "artifact_id": f"composition_photo:operator:{filename}",
            "category": "composition_photo",
            "role": "operator_upload",
            "path": str(photo_path),
            "summary": {
                "uploaded_at": sidecar_meta["uploaded_at"],
                "telegram_username": operator_username,
                "caption": sidecar_meta["caption"],
                "file_size_bytes": len(photo_bytes),
                "dimensions": dimensions,
                "phase_at_upload": phase_at_upload,
                "channels_mentioned": sidecar_meta["channels_mentioned"],
            },
        }
        self._append_composition_photo_to_metadata(experiment_id, artifact_entry)

        return {"filename": filename, "path": str(photo_path), "metadata": sidecar_meta}

    def _append_composition_photo_to_metadata(self, experiment_id: str, entry: dict[str, Any]) -> None:
        """Atomically append a composition_photo entry to artifact_index in metadata.json."""
        metadata_path = self._metadata_path(experiment_id)
        from cryodaq.core.atomic_write import atomic_write_text

        payload = self._read_metadata_payload(experiment_id)
        artifact_index: list[dict[str, Any]] = list(payload.get("artifact_index", []))
        artifact_index.append(entry)
        payload["artifact_index"] = artifact_index
        atomic_write_text(metadata_path, json.dumps(payload, ensure_ascii=False, indent=2))

    @_serialized_lifecycle_mutation
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
        self._assert_mutation_available()
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
        self._commit_transition("update", updated)
        return updated

    @_serialized_lifecycle_mutation
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
        self._assert_mutation_available()
        self._require_experiment_mode()
        active = self._require_active(experiment_id)

        finished_at = _parse_time(end_time) or datetime.now(UTC)
        if finished_at < active.start_time:
            raise ValueError("Experiment end_time cannot precede start_time.")

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
            end_time=finished_at,
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
        self._commit_transition(
            "finalize",
            finished,
            run_records=archive_snapshot["run_records"],
            artifact_index=archive_snapshot["artifact_index"],
            result_tables=archive_snapshot["result_tables"],
            summary_metadata=archive_snapshot["summary_metadata"],
        )
        # Phase 2e stage 1: Parquet archive — best-effort
        try:
            from cryodaq.storage.parquet_archive import export_experiment_readings_to_parquet

            export_experiment_readings_to_parquet(
                experiment_id=finished.experiment_id,
                start_time=finished.start_time,
                end_time=finished.end_time,
                sqlite_root=self._data_dir,
                output_path=finished.artifact_dir / "readings.parquet",
            )
        except ImportError:
            logger.warning("pyarrow not installed — skipping Parquet archive")
        except Exception:
            logger.exception(
                "Parquet archive export failed for %s — experiment finalized without parquet",
                finished.experiment_id,
            )

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
                f"experiment_id '{experiment_id}' does not match active '{self._active.experiment_id}'."  # noqa: E501
            )
        return self._active

    def _normalize_app_mode(self, raw: AppMode | str) -> AppMode:
        if isinstance(raw, AppMode):
            return raw
        value = _clean_text(raw).lower()
        if not value:
            raise ValueError("app_mode is required.")
        return AppMode(value)

    def _set_active(
        self,
        info: ExperimentInfo,
        *,
        state_revision: int | None = None,
        transition_receipt: dict[str, Any] | None | object = _UNSET,
    ) -> None:
        with self._mutation_lock:
            if self._active is None or self._active.experiment_id != info.experiment_id:
                self._operator_phase = None
            self._active = info
            self._state = ExperimentState(
                app_mode=self._state.app_mode,
                active_experiment_id=info.experiment_id,
            )
            try:
                self._write_state(
                    revision=state_revision,
                    transition_receipt=transition_receipt,
                )
            finally:
                # _write_state already follows the manager's in-memory commit.
                # If durability fails, preserve the exception while ensuring
                # the observational cut cannot publish the previous state.
                self._refresh_operator_snapshot()

    def _clear_active(
        self,
        *,
        state_revision: int | None = None,
        transition_receipt: dict[str, Any] | None | object = _UNSET,
    ) -> None:
        with self._mutation_lock:
            self._active = None
            self._operator_phase = None
            self._state = ExperimentState(app_mode=self._state.app_mode, active_experiment_id=None)
            try:
                self._write_state(
                    revision=state_revision,
                    transition_receipt=transition_receipt,
                )
            finally:
                self._refresh_operator_snapshot()

    def _refresh_operator_snapshot(self, *, force: bool = False) -> None:
        previous = self._operator_snapshot
        active = self._active
        candidate = (
            None if active is None else active.experiment_id,
            None if active is None else active.name,
            self._operator_phase if active is not None else None,
        )
        if not force and candidate == (
            previous.experiment_id,
            previous.experiment_name,
            previous.phase,
        ):
            return
        self._operator_snapshot = OperatorExperimentSnapshot(
            previous.revision + 1,
            *candidate,
        )

    def _state_fingerprint(
        self,
        *,
        revision: int,
        app_mode: AppMode,
        active_experiment_id: str | None,
    ) -> str:
        return _canonical_digest(
            {
                "schema_version": _STATE_SCHEMA_VERSION,
                "manager_incarnation": self._manager_incarnation,
                "revision": revision,
                "app_mode": app_mode.value,
                "active_experiment_id": active_experiment_id,
            }
        )

    def _state_cut(self) -> dict[str, Any]:
        receipt_fingerprint = (
            _canonical_digest(self._last_transition_receipt) if self._last_transition_receipt is not None else None
        )
        return {
            "manager_incarnation": self._manager_incarnation,
            "revision": self._state_revision,
            "app_mode": self._state.app_mode.value,
            "active_experiment_id": self._state.active_experiment_id,
            "state_fingerprint": self._state_fingerprint(
                revision=self._state_revision,
                app_mode=self._state.app_mode,
                active_experiment_id=self._state.active_experiment_id,
            ),
            "last_receipt_fingerprint": receipt_fingerprint,
        }

    def _load_state_authority(self) -> None:
        if not self._state_path.exists():
            if self._transition_path.exists():
                try:
                    json.loads(self._transition_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise RuntimeError("Experiment transition journal is unreadable.") from exc
                raise RuntimeError("Experiment transition has no durable predecessor state authority.")
            self._state = ExperimentState(app_mode=AppMode.EXPERIMENT, active_experiment_id=None)
            self._state_revision = 0
            self._last_transition_receipt = None
            self._write_state(revision=0, transition_receipt=None)
            return

        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError("Experiment state authority is unreadable.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Experiment state authority is invalid.")

        schema_version = payload.get("schema_version")
        if type(schema_version) is not int or schema_version not in {
            1,
            _STATE_SCHEMA_VERSION,
        }:
            raise RuntimeError("Experiment state authority has an unsupported schema.")
        legacy_keys = {
            "schema_version",
            "app_mode",
            "active_experiment_id",
            "updated_at",
        }
        v2_keys = {
            "schema_version",
            "app_mode",
            "active_experiment_id",
            "revision",
            "state_fingerprint",
            "last_transition_receipt",
            "last_transition_receipt_fingerprint",
            "manager_incarnation",
            "updated_at",
        }
        expected_keys = legacy_keys if schema_version == 1 else v2_keys
        if set(payload) != expected_keys:
            raise RuntimeError("Experiment state authority envelope is ambiguous.")
        if type(payload.get("app_mode")) is not str:
            raise RuntimeError("Experiment state application mode is invalid.")
        app_mode = self._normalize_app_mode(payload["app_mode"])
        active_experiment_id = payload.get("active_experiment_id")
        if active_experiment_id is not None and (type(active_experiment_id) is not str or not active_experiment_id):
            raise RuntimeError("Experiment state active identity is invalid.")
        updated_at = payload.get("updated_at")
        if type(updated_at) is not str:
            raise RuntimeError("Experiment state update timestamp is invalid.")
        try:
            parsed_updated_at = _parse_time(updated_at)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Experiment state update timestamp is invalid.") from exc
        if parsed_updated_at is None:
            raise RuntimeError("Experiment state update timestamp is invalid.")

        revision = 0 if schema_version == 1 else payload.get("revision")
        if type(revision) is not int or revision < 0:
            raise RuntimeError("Experiment state revision is invalid.")
        receipt = None if schema_version == 1 else payload.get("last_transition_receipt")
        if receipt is not None and not isinstance(receipt, dict):
            raise RuntimeError("Experiment state terminal receipt is invalid.")
        receipt_fingerprint = None if schema_version == 1 else payload.get("last_transition_receipt_fingerprint")
        if schema_version == _STATE_SCHEMA_VERSION:
            manager_incarnation = payload.get("manager_incarnation")
            if not _is_lower_hex(manager_incarnation, _HEX_ID_LENGTH):
                raise RuntimeError("Experiment manager incarnation is invalid.")
            self._manager_incarnation = manager_incarnation
            expected_fingerprint = self._state_fingerprint(
                revision=revision,
                app_mode=app_mode,
                active_experiment_id=active_experiment_id,
            )
            if (
                not _is_lower_hex(payload.get("state_fingerprint"), _SHA256_LENGTH)
                or payload.get("state_fingerprint") != expected_fingerprint
            ):
                raise RuntimeError("Experiment state fingerprint is invalid.")
            expected_receipt_fingerprint = _canonical_digest(receipt) if receipt is not None else None
            if receipt_fingerprint != expected_receipt_fingerprint or (
                receipt_fingerprint is not None and not _is_lower_hex(receipt_fingerprint, _SHA256_LENGTH)
            ):
                raise RuntimeError("Experiment state terminal receipt fingerprint is invalid.")
            if receipt is not None:
                receipt_keys = {
                    "schema",
                    "manager_incarnation",
                    "request_id",
                    "request_fingerprint",
                    "operation",
                    "experiment_id",
                    "experiment_fingerprint",
                    "predecessor_revision",
                    "predecessor_state_fingerprint",
                    "result_revision",
                    "result_active_experiment_id",
                    "result_state_fingerprint",
                }
                if (
                    set(receipt) != receipt_keys
                    or receipt.get("schema") != "experiment_transition_receipt_v2"
                    or receipt.get("manager_incarnation") != self._manager_incarnation
                    or not _is_lower_hex(receipt.get("request_id"), _HEX_ID_LENGTH)
                    or not _is_lower_hex(
                        receipt.get("request_fingerprint"),
                        _SHA256_LENGTH,
                    )
                    or not _is_lower_hex(
                        receipt.get("experiment_fingerprint"),
                        _SHA256_LENGTH,
                    )
                    or not _is_lower_hex(
                        receipt.get("predecessor_state_fingerprint"),
                        _SHA256_LENGTH,
                    )
                    or receipt.get("operation") not in {"create", "update", "finalize"}
                    or type(receipt.get("experiment_id")) is not str
                    or not receipt.get("experiment_id")
                    or type(receipt.get("predecessor_revision")) is not int
                    or receipt.get("predecessor_revision") < 0
                    or receipt.get("result_revision") != receipt.get("predecessor_revision") + 1
                    or receipt.get("result_revision") != revision
                    or receipt.get("result_active_experiment_id") != active_experiment_id
                    or receipt.get("result_state_fingerprint") != expected_fingerprint
                    or (
                        receipt.get("operation") == "finalize"
                        and receipt.get("result_active_experiment_id") is not None
                    )
                    or (
                        receipt.get("operation") in {"create", "update"}
                        and receipt.get("result_active_experiment_id") != receipt.get("experiment_id")
                    )
                ):
                    raise RuntimeError("Experiment state terminal receipt is invalid.")
        elif self._transition_path.exists():
            # A legacy journal cannot be upgraded safely because it has no
            # predecessor cut. Preserve both files for operator recovery.
            self._state = ExperimentState(app_mode=app_mode, active_experiment_id=active_experiment_id)
            self._state_revision = revision
            self._last_transition_receipt = receipt
            return

        self._state = ExperimentState(app_mode=app_mode, active_experiment_id=active_experiment_id)
        self._state_revision = revision
        self._last_transition_receipt = dict(receipt) if receipt is not None else None
        if schema_version == 1:
            self._write_state(revision=revision, transition_receipt=receipt)

    def _load_state(self) -> None:
        self._load_state_authority()
        active_experiment_id = self._state.active_experiment_id
        if active_experiment_id:
            active = self._read_experiment_from_metadata(active_experiment_id)
            if active is not None and active.status is ExperimentStatus.RUNNING:
                self._active = active
            else:
                self._clear_active()

    def _write_state(
        self,
        *,
        revision: int | None = None,
        transition_receipt: dict[str, Any] | None | object = _UNSET,
    ) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        next_revision = self._state_revision + 1 if revision is None else revision
        if type(next_revision) is not int or next_revision < 0:
            raise RuntimeError("Experiment state revision is invalid.")
        next_receipt = None if transition_receipt is _UNSET else transition_receipt
        if next_receipt is not None and not isinstance(next_receipt, dict):
            raise RuntimeError("Experiment state terminal receipt is invalid.")
        payload = {
            "schema_version": _STATE_SCHEMA_VERSION,
            **self._state.to_payload(),
            "revision": next_revision,
            "state_fingerprint": self._state_fingerprint(
                revision=next_revision,
                app_mode=self._state.app_mode,
                active_experiment_id=self._state.active_experiment_id,
            ),
            "last_transition_receipt": next_receipt,
            "last_transition_receipt_fingerprint": (
                _canonical_digest(next_receipt) if next_receipt is not None else None
            ),
            "manager_incarnation": self._manager_incarnation,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        from cryodaq.core.atomic_write import atomic_write_text

        atomic_write_text(self._state_path, json.dumps(payload, ensure_ascii=False, indent=2))
        self._state_revision = next_revision
        self._last_transition_receipt = dict(next_receipt) if isinstance(next_receipt, dict) else None

    def _commit_transition(
        self,
        operation: str,
        info: ExperimentInfo,
        *,
        run_records: list[RunRecord] | None = None,
        artifact_index: list[dict[str, Any]] | None = None,
        result_tables: list[dict[str, Any]] | None = None,
        summary_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Durably journal and apply one identity-bound CAS transition."""

        if self._transition_path.exists():
            self._recover_transition()
        self._load_state_authority()
        predecessor = self._state_cut()
        request_id = uuid.uuid4().hex
        payload: dict[str, Any] = {
            "schema_version": _TRANSITION_SCHEMA_VERSION,
            "manager_incarnation": self._manager_incarnation,
            "request_id": request_id,
            "operation": operation,
            "experiment": info.to_payload(),
            "predecessor": predecessor,
        }
        if run_records is not None:
            payload["run_records"] = [
                item.to_payload() if isinstance(item, RunRecord) else dict(item) for item in run_records
            ]
        if artifact_index is not None:
            payload["artifact_index"] = [dict(item) for item in artifact_index]
        if result_tables is not None:
            payload["result_tables"] = [dict(item) for item in result_tables]
        if summary_metadata is not None:
            payload["summary_metadata"] = dict(summary_metadata)
        request_material = dict(payload)
        request_fingerprint = _canonical_digest(request_material)
        payload["request_fingerprint"] = request_fingerprint

        result_active_id = None if operation == "finalize" else info.experiment_id
        result_revision = predecessor["revision"] + 1
        result_state_fingerprint = self._state_fingerprint(
            revision=result_revision,
            app_mode=AppMode(predecessor["app_mode"]),
            active_experiment_id=result_active_id,
        )
        payload["terminal_receipt"] = {
            "schema": "experiment_transition_receipt_v2",
            "manager_incarnation": self._manager_incarnation,
            "request_id": request_id,
            "request_fingerprint": request_fingerprint,
            "operation": operation,
            "experiment_id": info.experiment_id,
            "experiment_fingerprint": _canonical_digest(info.to_payload()),
            "predecessor_revision": predecessor["revision"],
            "predecessor_state_fingerprint": predecessor["state_fingerprint"],
            "result_revision": result_revision,
            "result_active_experiment_id": result_active_id,
            "result_state_fingerprint": result_state_fingerprint,
        }

        from cryodaq.core.atomic_write import atomic_write_text

        atomic_write_text(
            self._transition_path,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        self._apply_transition(payload)
        self._transition_path.unlink(missing_ok=False)

    def _recover_transition(self) -> None:
        """Replay an interrupted lifecycle transition before accepting commands."""

        if not self._transition_path.exists():
            return
        if self._transition_path.stat().st_size > 16 * 1024 * 1024:
            raise RuntimeError("Experiment transition journal exceeds its safety bound.")
        try:
            payload = json.loads(self._transition_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError("Experiment transition journal is unreadable.") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != _TRANSITION_SCHEMA_VERSION:
            raise RuntimeError("Experiment transition journal has an unsupported schema.")
        self._load_state_authority()
        self._apply_transition(payload)
        self._transition_path.unlink(missing_ok=False)
        self._load_state()

    def _validate_transition_authority(
        self,
        payload: dict[str, Any],
        info: ExperimentInfo,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        optional_keys = {
            "run_records",
            "artifact_index",
            "result_tables",
            "summary_metadata",
        }
        required_keys = {
            "schema_version",
            "manager_incarnation",
            "request_id",
            "request_fingerprint",
            "operation",
            "experiment",
            "predecessor",
            "terminal_receipt",
        }
        if set(payload) - required_keys - optional_keys or not required_keys.issubset(payload):
            raise RuntimeError("Experiment transition envelope is ambiguous.")
        manager_incarnation = payload.get("manager_incarnation")
        request_id = payload.get("request_id")
        request_fingerprint = payload.get("request_fingerprint")
        if not _is_lower_hex(manager_incarnation, _HEX_ID_LENGTH):
            raise RuntimeError("Experiment transition manager incarnation is invalid.")
        if manager_incarnation != self._manager_incarnation:
            raise RuntimeError("Experiment transition belongs to a different manager incarnation.")
        if not _is_lower_hex(request_id, _HEX_ID_LENGTH):
            raise RuntimeError("Experiment transition request identity is invalid.")
        if not _is_lower_hex(request_fingerprint, _SHA256_LENGTH):
            raise RuntimeError("Experiment transition request fingerprint is invalid.")
        request_material = {
            key: value for key, value in payload.items() if key not in {"request_fingerprint", "terminal_receipt"}
        }
        if _canonical_digest(request_material) != request_fingerprint:
            raise RuntimeError("Experiment transition request fingerprint does not match its payload.")

        predecessor = payload.get("predecessor")
        if not isinstance(predecessor, dict) or set(predecessor) != {
            "manager_incarnation",
            "revision",
            "app_mode",
            "active_experiment_id",
            "state_fingerprint",
            "last_receipt_fingerprint",
        }:
            raise RuntimeError("Experiment transition predecessor authority is invalid.")
        if predecessor.get("manager_incarnation") != manager_incarnation:
            raise RuntimeError("Experiment transition predecessor incarnation is inconsistent.")
        revision = predecessor.get("revision")
        if type(revision) is not int or revision < 0:
            raise RuntimeError("Experiment transition predecessor revision is invalid.")
        try:
            predecessor_mode = AppMode(predecessor.get("app_mode"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Experiment transition predecessor mode is invalid.") from exc
        predecessor_active_id = predecessor.get("active_experiment_id")
        if predecessor_active_id is not None and (type(predecessor_active_id) is not str or not predecessor_active_id):
            raise RuntimeError("Experiment transition predecessor identity is invalid.")
        expected_predecessor_fingerprint = self._state_fingerprint(
            revision=revision,
            app_mode=predecessor_mode,
            active_experiment_id=predecessor_active_id,
        )
        if predecessor.get("state_fingerprint") != expected_predecessor_fingerprint:
            raise RuntimeError("Experiment transition predecessor fingerprint is invalid.")
        operation = payload["operation"]
        if predecessor_mode is not AppMode.EXPERIMENT:
            raise RuntimeError("Experiment transition predecessor mode is not authoritative.")
        if operation == "create":
            if predecessor_active_id is not None:
                raise RuntimeError("Create transition predecessor already has an active experiment.")
        elif predecessor_active_id != info.experiment_id:
            raise RuntimeError("Experiment transition predecessor identity does not match its target.")
        last_receipt_fingerprint = predecessor.get("last_receipt_fingerprint")
        if last_receipt_fingerprint is not None and not _is_lower_hex(
            last_receipt_fingerprint,
            _SHA256_LENGTH,
        ):
            raise RuntimeError("Experiment transition predecessor receipt is invalid.")

        result_active_id = None if operation == "finalize" else info.experiment_id
        result_revision = revision + 1
        result_state_fingerprint = self._state_fingerprint(
            revision=result_revision,
            app_mode=predecessor_mode,
            active_experiment_id=result_active_id,
        )
        expected_receipt = {
            "schema": "experiment_transition_receipt_v2",
            "manager_incarnation": manager_incarnation,
            "request_id": request_id,
            "request_fingerprint": request_fingerprint,
            "operation": operation,
            "experiment_id": info.experiment_id,
            "experiment_fingerprint": _canonical_digest(info.to_payload()),
            "predecessor_revision": revision,
            "predecessor_state_fingerprint": expected_predecessor_fingerprint,
            "result_revision": result_revision,
            "result_active_experiment_id": result_active_id,
            "result_state_fingerprint": result_state_fingerprint,
        }
        receipt = payload.get("terminal_receipt")
        if receipt != expected_receipt:
            raise RuntimeError("Experiment transition terminal receipt is invalid.")

        current = self._state_cut()
        if current == predecessor:
            return predecessor, expected_receipt, False
        exact_result = (
            current["manager_incarnation"] == manager_incarnation
            and current["revision"] == result_revision
            and current["app_mode"] == predecessor_mode.value
            and current["active_experiment_id"] == result_active_id
            and current["state_fingerprint"] == result_state_fingerprint
            and self._last_transition_receipt == expected_receipt
        )
        if exact_result:
            return predecessor, expected_receipt, True
        raise RuntimeError("Experiment transition predecessor is stale or its durable receipt is equivocal.")

    def _apply_transition(self, payload: dict[str, Any]) -> None:
        operation = payload.get("operation")
        if operation not in {"create", "update", "finalize"}:
            raise RuntimeError("Experiment transition operation is invalid.")
        raw_info = payload.get("experiment")
        if not isinstance(raw_info, dict):
            raise RuntimeError("Experiment transition has no exact experiment payload.")
        info = self._experiment_info_from_payload(raw_info)
        predecessor, terminal_receipt, already_committed = self._validate_transition_authority(payload, info)
        if already_committed:
            return
        if operation in {"create", "update"}:
            if info.status is not ExperimentStatus.RUNNING or info.end_time is not None:
                raise RuntimeError("Active transition must carry exact RUNNING state.")
        elif info.status is ExperimentStatus.RUNNING or info.end_time is None:
            raise RuntimeError("Finalize transition must carry exact terminal state.")

        raw_records = payload.get("run_records")
        run_records = None
        if raw_records is not None:
            if not isinstance(raw_records, list):
                raise RuntimeError("Experiment transition run_records are invalid.")
            run_records = [RunRecord.from_payload(item) for item in raw_records if isinstance(item, dict)]
            if len(run_records) != len(raw_records):
                raise RuntimeError("Experiment transition run_records contain invalid entries.")

        def exact_dict_list(key: str) -> list[dict[str, Any]] | None:
            raw = payload.get(key)
            if raw is None:
                return None
            if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
                raise RuntimeError(f"Experiment transition {key} is invalid.")
            return [dict(item) for item in raw]

        artifact_index = exact_dict_list("artifact_index")
        result_tables = exact_dict_list("result_tables")
        raw_summary = payload.get("summary_metadata")
        if raw_summary is not None and not isinstance(raw_summary, dict):
            raise RuntimeError("Experiment transition summary_metadata is invalid.")

        if operation == "create":
            self._write_start(info)
        else:
            self._write_end(info)
        self._write_artifact(
            info,
            run_records=run_records,
            artifact_index=artifact_index,
            result_tables=result_tables,
            summary_metadata=dict(raw_summary) if raw_summary is not None else None,
        )
        if operation in {"create", "update"}:
            self._set_active(
                info,
                state_revision=predecessor["revision"] + 1,
                transition_receipt=terminal_receipt,
            )
        else:
            self._clear_active(
                state_revision=predecessor["revision"] + 1,
                transition_receipt=terminal_receipt,
            )

    def _experiment_info_from_payload(self, experiment: dict[str, Any]) -> ExperimentInfo:
        experiment_id = _clean_text(experiment.get("experiment_id"))
        name = _clean_text(experiment.get("name"))
        operator = _clean_text(experiment.get("operator"))
        start_time = _parse_time(experiment.get("start_time"))
        end_time = _parse_time(experiment.get("end_time"))
        status_raw = _clean_text(experiment.get("status"))
        if not experiment_id or not name or not operator or start_time is None or not status_raw:
            raise ValueError("Experiment identity, operator, start_time, and status must be explicit.")
        status = ExperimentStatus(status_raw)
        if end_time is not None and end_time < start_time:
            raise ValueError("Experiment end_time cannot precede start_time.")
        if status is ExperimentStatus.RUNNING and end_time is not None:
            raise ValueError("RUNNING experiment cannot carry end_time.")
        if status is not ExperimentStatus.RUNNING and end_time is None:
            raise ValueError("Terminal experiment must carry end_time.")
        return ExperimentInfo(
            experiment_id=experiment_id,
            name=name,
            title=_clean_text(experiment.get("title")) or name,
            template_id=_clean_text(experiment.get("template_id")) or "custom",
            operator=operator,
            cryostat=_clean_text(experiment.get("cryostat")),
            sample=_clean_text(experiment.get("sample")),
            description=_clean_text(experiment.get("description")),
            notes=_clean_text(experiment.get("notes")),
            start_time=start_time,
            end_time=end_time,
            status=status,
            config_snapshot=dict(experiment.get("config_snapshot") or {}),
            custom_fields=_normalize_custom_fields(experiment.get("custom_fields")),
            report_enabled=bool(experiment.get("report_enabled", True)),
            sections=tuple(str(item) for item in experiment.get("sections", []) if str(item).strip()),
            artifact_dir=self._artifact_dir(experiment_id),
            metadata_path=self._metadata_path(experiment_id),
            retroactive=bool(experiment.get("retroactive", False)),
        )

    def _read_experiment_from_metadata(self, experiment_id: str) -> ExperimentInfo | None:
        metadata_path = self._metadata_path(experiment_id)
        if not metadata_path.exists():
            return None
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        experiment = payload.get("experiment")
        if not isinstance(experiment, dict):
            raise ValueError("Experiment metadata has no exact experiment payload.")
        info = self._experiment_info_from_payload(experiment)
        if info.experiment_id != experiment_id:
            raise ValueError("Experiment metadata identity does not match its directory.")
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
                report_sections=tuple(str(item) for item in raw.get("report_sections", []) if str(item).strip()),
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

    def _persisted_running_experiment_ids(self) -> set[str]:
        """Return exact RUNNING identities across every daily lifecycle DB."""

        running: set[str] = set()
        if not self._data_dir.exists():
            return running
        for db_path in self._data_dir.glob("data_????-??-??.db"):
            conn = sqlite3.connect(str(db_path), timeout=10)
            try:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='experiments'"
                ).fetchone()
                if exists is None:
                    continue
                for row in conn.execute("SELECT experiment_id FROM experiments WHERE status = 'RUNNING'"):
                    experiment_id = _clean_text(row[0])
                    if not experiment_id:
                        raise RuntimeError(f"Persisted RUNNING row has no identity in {db_path.name}.")
                    running.add(experiment_id)
            finally:
                conn.close()
        return running

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
        conn.execute(SCHEMA_SINGLE_RUNNING_EXPERIMENT)
        conn.commit()
        return conn

    def _write_start(self, info: ExperimentInfo) -> None:
        conn = self._get_connection(info.start_time)
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT name, operator, start_time, status FROM experiments WHERE experiment_id = ?",
                (info.experiment_id,),
            ).fetchone()
            if existing is not None:
                expected = (
                    info.name,
                    info.operator,
                    info.start_time.isoformat(),
                    info.status.value,
                )
                if tuple(existing) != expected:
                    raise RuntimeError("Persisted experiment identity collides with different evidence.")
                conn.commit()
                return
            conn.execute(
                "INSERT INTO experiments ("
                "experiment_id, name, operator, cryostat, sample, description, start_time, end_time, "  # noqa: E501
                "status, config_snapshot, template_id, title, notes, custom_fields, report_enabled, "  # noqa: E501
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
            cursor = conn.execute(
                "UPDATE experiments SET "
                "name = ?, title = ?, sample = ?, description = ?, notes = ?, end_time = ?, status = ?, "  # noqa: E501
                "custom_fields = ?, report_enabled = ?, template_id = ?, artifact_dir = ?, metadata_path = ?, "  # noqa: E501
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
            if cursor.rowcount != 1:
                raise RuntimeError(f"Persisted experiment row is missing for {info.experiment_id}.")
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
            **{
                key: value
                for key, value in existing_payload.items()
                if key not in {"experiment", "template", "data_range", "artifacts", "run_records"}
            },
            "schema_version": int(existing_payload.get("schema_version", 1) or 1),
            "experiment": info.to_payload(),
            "template": template.to_payload(),
            "data_range": {
                "start_time": info.start_time.isoformat(),
                "end_time": info.end_time.isoformat() if info.end_time else None,
                "daily_db_files": sorted(
                    self._all_db_names_for_range(
                        info.start_time,
                        info.end_time or info.start_time,
                    )
                ),
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
                    artifact_index if artifact_index is not None else list(existing_payload.get("artifact_index", []))
                )
            ],
            "result_tables": [
                dict(item)
                for item in (
                    result_tables if result_tables is not None else list(existing_payload.get("result_tables", []))
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

    @_serialized_lifecycle
    def resolve_operator_log_scope(
        self,
        *,
        expected_experiment_id: str | None,
        unbound: bool,
    ) -> str | None:
        """Resolve an operator-log target without implicit current-state binding."""

        if type(unbound) is not bool:
            raise ValueError("unbound must be exactly bool")
        if unbound:
            if expected_experiment_id is not None:
                raise ValueError("unbound operator log entry cannot also name an experiment")
            return None
        if type(expected_experiment_id) is not str or not expected_experiment_id:
            raise ValueError("expected_experiment_id is required unless the entry is explicitly unbound")
        if self._active is None or self._active.experiment_id != expected_experiment_id:
            raise ExperimentIdentityMismatchError(
                "Active experiment does not match expected_experiment_id; "
                "the operator log command is stale and was not applied."
            )
        return expected_experiment_id

    @_serialized_lifecycle_mutation
    def advance_phase(
        self,
        phase: str,
        operator: str = "",
        *,
        expected_experiment_id: str,
    ) -> dict[str, Any]:
        """Transition the explicitly identified active experiment to a phase.

        The expected identifier is mandatory so a delayed command submitted
        for a finalized experiment can never mutate a newer active experiment.
        The lifecycle lock keeps the identity check and metadata write in one
        serialized authority interval.
        """
        if type(expected_experiment_id) is not str or not expected_experiment_id:
            raise ValueError("expected_experiment_id must be a non-empty string")
        if self._active is None:
            raise RuntimeError("No active experiment.")
        if self._active.experiment_id != expected_experiment_id:
            raise ExperimentIdentityMismatchError(
                "Experiment identity mismatch: active experiment does not match expected_experiment_id; "
                "the phase command is stale and was not applied."
            )
        with self.experiment_cas(expected_experiment_id):
            return self._advance_phase_locked(phase, operator, expected_experiment_id)

    def _advance_phase_locked(
        self,
        phase: str,
        operator: str = "",
        expected_experiment_id: str = "",
    ) -> dict[str, Any]:
        """Transition phase only for the exact currently-authoritative experiment."""
        if self._active is None:
            raise RuntimeError("No active experiment.")
        if type(expected_experiment_id) is not str or expected_experiment_id != self._active.experiment_id:
            raise ExperimentIdentityMismatchError("Experiment identity mismatch.")
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

        self._operator_phase = phase
        self._refresh_operator_snapshot()

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

        readings_snapshot = self._load_experiment_readings(info)
        readings = list(readings_snapshot.rows)
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

        # Parquet archive — deferred to finalize_experiment hook (Phase 2e).
        # The streaming export reads from SQLite directly, avoiding memory
        # duplication of the readings list.

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
            channel_filter=lambda item: (
                "pressure" in str(item["channel"]).lower() or str(item["unit"]).lower() in {"mbar", "pa"}
            ),
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
            "measured_values_complete": readings_snapshot.complete,
            "measured_values_truncated": readings_snapshot.truncated,
            "measured_values_issues": list(readings_snapshot.issues),
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

    def _load_experiment_readings(self, info: ExperimentInfo) -> ExperimentReadingsSnapshot:
        if info.end_time is None:
            return ExperimentReadingsSnapshot((), False, False, ("missing_end_time",))

        reader = ArchiveReader(self._data_dir, self._data_dir / "archive")
        campaign_start = info.start_time.astimezone(UTC)
        cursor_end = info.end_time.astimezone(UTC) + timedelta(microseconds=1)
        deadline = time.monotonic() + 30.0
        max_total_points = 500_000
        max_points_per_channel = 100_000
        max_retained_bytes = 32 * 1024 * 1024
        rows_newest_first: list[dict[str, Any]] = []
        per_channel: dict[str, int] = {}
        retained_bytes = 0
        issues: list[str] = []
        complete = True
        truncated = False

        while cursor_end > campaign_start:
            if time.monotonic() >= deadline:
                issues.append("deadline")
                complete = False
                break
            chunk_start = max(campaign_start, cursor_end - timedelta(hours=168))
            result = reader.query_reading_rows_bounded(
                start=chunk_start,
                end=cursor_end,
                channels=None,
                max_channels=64,
                max_points_per_channel=max_points_per_channel,
                max_total_points=max_total_points,
                max_retained_bytes=max_retained_bytes,
                deadline_monotonic=deadline,
            )
            complete = complete and result.complete
            truncated = truncated or result.truncated
            issues.extend(f"{issue.code.value}:{issue.source}" for issue in result.issues)
            if result.issue_overflow:
                issues.append(f"issue_overflow:{result.issue_overflow}")
            for row in reversed(result.rows):
                channel_count = per_channel.get(row.channel, 0)
                encoded_size = (
                    96
                    + len(row.instrument_id.encode("utf-8"))
                    + len(row.channel.encode("utf-8"))
                    + len(row.unit.encode("utf-8"))
                    + len(row.status.encode("utf-8"))
                )
                if (
                    len(rows_newest_first) >= max_total_points
                    or channel_count >= max_points_per_channel
                    or retained_bytes + encoded_size > max_retained_bytes
                ):
                    truncated = True
                    complete = False
                    continue
                rows_newest_first.append(
                    {
                        "timestamp": datetime.fromtimestamp(row.timestamp, tz=UTC),
                        "instrument_id": row.instrument_id,
                        "channel": row.channel,
                        "value": float("nan") if row.value is None else row.value,
                        "unit": row.unit,
                        "status": row.status,
                    }
                )
                per_channel[row.channel] = channel_count + 1
                retained_bytes += encoded_size
            cursor_end = chunk_start

        rows_newest_first.sort(key=lambda item: item["timestamp"])
        return ExperimentReadingsSnapshot(
            tuple(rows_newest_first),
            complete and not issues and not truncated and cursor_end <= campaign_start,
            truncated,
            tuple(dict.fromkeys(issues)),
        )

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
                if not source.exists() or source.is_symlink() or not source.is_file():
                    continue
                source = source.resolve(strict=True)
                artifact_root = (info.artifact_dir or self._artifact_dir(info.experiment_id)).resolve(strict=True)
                source_digest = self._sha256_file(source)
                if source.is_relative_to(artifact_root):
                    target = source
                    materialization = "owned"
                else:
                    target_dir = (
                        archive_root
                        / "runs"
                        / self._safe_slug(record.source_tab)
                        / self._safe_slug(record.source_run_id)
                    )
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / (f"{source.stem}.{source_digest[:16]}{source.suffix.lower()}")
                    self._materialize_immutable_copy(source, target, source_digest)
                    materialization = "immutable_copy"
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
                            "materialization": materialization,
                            "sha256": source_digest,
                            "size_bytes": target.stat().st_size,
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

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
        return digest.hexdigest()

    @classmethod
    def _materialize_immutable_copy(
        cls,
        source: Path,
        target: Path,
        expected_digest: str,
    ) -> None:
        """Copy one stable source into an exclusive content-addressed target."""

        before = source.stat()
        descriptor, raw_temp = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        os.close(descriptor)
        temp_path = Path(raw_temp)
        try:
            with source.open("rb") as source_handle, temp_path.open("wb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
                target_handle.flush()
                os.fsync(target_handle.fileno())
            after = source.stat()
            if (
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                or cls._sha256_file(source) != expected_digest
                or cls._sha256_file(temp_path) != expected_digest
            ):
                raise RuntimeError("Run artifact changed while being materialized.")
            try:
                os.link(temp_path, target)
            except FileExistsError:
                if not target.is_file() or target.is_symlink():
                    raise RuntimeError("Run artifact target collides with unsafe filesystem state.")
                if cls._sha256_file(target) != expected_digest:
                    raise RuntimeError("Run artifact target collides with different content.")
            except OSError as exc:
                raise RuntimeError("Atomic exclusive artifact materialization is unavailable.") from exc
            else:
                temp_path.unlink()
                target.chmod(target.stat().st_mode & ~0o222)
        finally:
            temp_path.unlink(missing_ok=True)

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
                    writer.writerow(
                        [
                            record.record_id,
                            record.source_tab,
                            record.run_type,
                            key,
                            json.dumps(value, ensure_ascii=False),
                        ]
                    )
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
                        reader = csv.DictReader(line for line in handle if not line.startswith("#"))
                        for item in reader:
                            try:
                                row = {
                                    "temperature_k": float(item.get("T_avg_K", "")),
                                    "conductance_wk": float(item.get("G_WK", "")),
                                    "resistance_kw": float(item.get("R_KW", "")),
                                }
                            except (TypeError, ValueError):
                                continue
                            if all(math.isfinite(value) for value in row.values()):
                                rows.append(row)
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


# ---------------------------------------------------------------------------
# F27 helpers (module-level)
# ---------------------------------------------------------------------------


def _validate_photo_dimensions(data: bytes) -> dict[str, int] | None:
    """Return {'width': w, 'height': h} if bytes are a valid JPEG/PNG, else None."""
    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(data))
        img.verify()
        # verify() closes the file; reopen to read dimensions
        img = Image.open(BytesIO(data))
        return {"width": img.width, "height": img.height}
    except Exception as exc:
        logger.error("Photo validation failed: %s", exc)
        return None
