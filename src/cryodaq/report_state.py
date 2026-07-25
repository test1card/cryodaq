"""Lightweight durable contracts for out-of-process report generation.

This module deliberately depends only on the standard library plus CryoDAQ's
atomic-write helper. It is safe for engine/assistant imports: no renderer,
plotting, DOCX, driver, or GUI module is imported here.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cryodaq.core.atomic_write import atomic_write_text

SCHEMA_VERSION = 1
MAX_JSON_BYTES = 128 * 1024
MAX_SOURCE_FILES = 2_048
MAX_SOURCE_FILE_BYTES = 256 * 1024 * 1024
MAX_SOURCE_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_GENERATED_FILES = 2_048
MAX_GENERATED_FILE_BYTES = 256 * 1024 * 1024
MAX_GENERATED_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_GENERATION_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{15,127}\Z")
_REPORT_STATUSES = frozenset({"PENDING", "RUNNING", "SUCCEEDED", "FAILED"})
ALLOWED_REPORT_INPUT_SUFFIXES = frozenset(
    {
        ".json",
        ".csv",
        ".parquet",
        ".png",
        ".jpg",
        ".jpeg",
        ".yaml",
        ".yml",
        ".docx",
        ".pdf",
        ".xlsx",
        ".xls",
        ".txt",
    }
)


class ReportContractError(ValueError):
    """A report state, path, manifest, or fingerprint violates its contract."""


class ReportIOError(ReportContractError):
    """A retryable filesystem/text-decoding failure, not invalid durable content."""


def load_active_experiment_id(data_dir: Path) -> str | None:
    """Read the atomic active-experiment guard, failing closed on corruption."""
    root = Path(data_dir).resolve()
    path = root / "experiment_state.json"
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise ReportContractError("active experiment state must be a bounded regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportContractError("active experiment state is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ReportContractError("active experiment state root must be a mapping")
    required = {"schema_version", "app_mode", "active_experiment_id", "updated_at"}
    if set(payload) != required:
        raise ReportContractError("active experiment state has unexpected fields")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ReportContractError("active experiment state schema is invalid")
    if payload["app_mode"] not in {"experiment", "debug"}:
        raise ReportContractError("active experiment app_mode is invalid")
    updated_at = payload["updated_at"]
    if not isinstance(updated_at, str) or not updated_at.strip():
        raise ReportContractError("active experiment updated_at is invalid")
    try:
        parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        timestamp = parsed.timestamp()
        if not math.isfinite(timestamp) or timestamp > time.time() + 300:
            raise ValueError("future or non-finite timestamp")
    except (OverflowError, ValueError) as exc:
        raise ReportContractError("active experiment updated_at is invalid") from exc
    value = payload["active_experiment_id"]
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReportContractError("active_experiment_id must be a string or null")
    return validate_experiment_id(value)


def automatic_report_eligible(
    experiment_root: Path,
    *,
    active_experiment_id: str | None,
) -> bool:
    """Strictly validate terminal metadata used as an automatic work request."""
    root = Path(experiment_root)
    if root.is_symlink() or not root.is_dir():
        raise ReportContractError("experiment root must be a real directory")
    resolved_root = root.resolve()
    experiment_id = validate_experiment_id(root.name)
    if experiment_id == active_experiment_id:
        return False
    metadata_path = root / "metadata.json"
    if metadata_path.is_symlink() or not metadata_path.is_file():
        raise ReportContractError("metadata must be a regular file")
    if metadata_path.resolve().parent != resolved_root:
        raise ReportContractError("metadata escapes the experiment root")
    if metadata_path.stat().st_size > MAX_JSON_BYTES:
        raise ReportContractError("metadata exceeds the size limit")
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ReportIOError("metadata could not be read") from exc
    except json.JSONDecodeError as exc:
        raise ReportContractError("metadata is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ReportContractError("metadata root must be a mapping")
    experiment = payload.get("experiment")
    template = payload.get("template", {})
    if not isinstance(experiment, dict) or not isinstance(template, dict):
        raise ReportContractError("metadata experiment/template must be mappings")
    if experiment.get("experiment_id") != experiment_id:
        raise ReportContractError("metadata experiment_id does not match its directory")
    status = experiment.get("status")
    if status == "RUNNING":
        return False
    if status not in {"COMPLETED", "ABORTED"}:
        raise ReportContractError("metadata status is not a supported terminal value")
    ended = experiment.get("end_time")
    if not isinstance(ended, str) or not ended.strip():
        raise ReportContractError("terminal metadata end_time is required")
    try:
        parsed = datetime.fromisoformat(ended.replace("Z", "+00:00"))
        if not math.isfinite(parsed.timestamp()):
            raise ValueError("non-finite timestamp")
    except (OverflowError, ValueError) as exc:
        raise ReportContractError("terminal metadata end_time is invalid") from exc
    enabled = (
        experiment["report_enabled"]
        if "report_enabled" in experiment
        else template.get("report_enabled")
    )
    if type(enabled) is not bool:
        raise ReportContractError("report_enabled must be a boolean")
    if enabled is False:
        return False
    retroactive = experiment.get("retroactive")
    if type(retroactive) is not bool:
        raise ReportContractError("retroactive must be a boolean")
    return retroactive is False


@dataclass(frozen=True, slots=True)
class ReportPaths:
    experiment_root: Path
    reports: Path
    staging_root: Path
    generations_root: Path
    current_manifest: Path


def _one_component(value: str, *, field: str, max_length: int = 255) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ReportContractError(f"{field} must be a non-empty bounded string")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise ReportContractError(f"{field} must be exactly one path component")
    if value.startswith("-") or Path(value).is_absolute() or any(ord(char) < 32 for char in value):
        raise ReportContractError(f"{field} contains forbidden characters")
    return value


def validate_experiment_id(experiment_id: str) -> str:
    return _one_component(experiment_id, field="experiment_id")


def validate_generation_id(generation_id: str) -> str:
    if not isinstance(generation_id, str) or not _GENERATION_RE.fullmatch(generation_id):
        raise ReportContractError("generation_id must contain 16-128 ASCII letters, digits, '_' or '-'")
    return generation_id


def _contained(path: Path, root: Path, *, field: str) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ReportContractError(f"{field} escapes its trusted root")
    return resolved


def _reject_symlink_components(path: Path, root: Path, *, field: str) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ReportContractError(f"{field} escapes its trusted root") from exc
    if ".." in relative.parts:
        raise ReportContractError(f"{field} contains parent traversal")
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ReportContractError(f"{field} contains a symlink component")


def _report_directory(
    path: Path,
    experiment_root: Path,
    *,
    field: str,
    create: bool,
) -> Path:
    if path.is_symlink():
        raise ReportContractError(f"{field} must not be a symlink")
    if create:
        path.mkdir(parents=False, exist_ok=True)
    if path.exists() and not path.is_dir():
        raise ReportContractError(f"{field} must be a directory")
    resolved = _contained(path, experiment_root, field=field)
    if path.exists() and resolved.is_symlink():
        raise ReportContractError(f"{field} must not be a symlink")
    return resolved


def resolve_report_paths(
    experiment_root: Path,
    *,
    create_reports: bool = False,
    create_staging: bool = False,
    create_generations: bool = False,
) -> ReportPaths:
    """Resolve and validate every fixed report output ancestor.

    Existing ``reports``, ``.staging``, and ``generations`` components must be
    real directories, never symlinks. Every returned path is resolved beneath
    the real experiment root, including when the leaf does not exist yet.
    """
    original_root = Path(experiment_root)
    if original_root.is_symlink():
        raise ReportContractError("experiment root must not be a symlink")
    root = original_root.resolve()
    if not root.is_dir():
        raise ReportContractError("experiment root must be a directory")
    reports = _report_directory(
        root / "reports",
        root,
        field="reports directory",
        create=create_reports or create_staging or create_generations,
    )
    staging = _report_directory(
        reports / ".staging",
        root,
        field="staging directory",
        create=create_staging,
    )
    generations = _report_directory(
        reports / "generations",
        root,
        field="generations directory",
        create=create_generations,
    )
    raw_current = reports / "current_report.json"
    _reject_symlink_components(raw_current, root, field="current manifest")
    current = _contained(raw_current, root, field="current manifest")
    return ReportPaths(root, reports, staging, generations, current)


def resolve_report_artifact(
    path: Path,
    report_paths: ReportPaths,
    *,
    field: str,
    required: bool,
    directory: bool = False,
) -> Path:
    """Validate one report artifact beneath the trusted reports root."""
    candidate = Path(path)
    _reject_symlink_components(candidate, report_paths.reports, field=field)
    resolved = _contained(candidate, report_paths.reports, field=field)
    _contained(resolved, report_paths.experiment_root, field=field)
    if required:
        if directory:
            if not resolved.is_dir() or resolved.is_symlink():
                raise ReportContractError(f"{field} must be a real directory")
        elif not resolved.is_file() or resolved.is_symlink():
            raise ReportContractError(f"{field} must be a regular file")
    return resolved


def resolve_experiment_dir(data_dir: Path, experiment_id: str) -> Path:
    """Resolve a real, non-symlink experiment directory under ``data_dir``."""
    experiment_id = validate_experiment_id(experiment_id)
    data_root = Path(data_dir).resolve()
    raw_root = data_root / "experiments"
    if raw_root.is_symlink():
        raise ReportContractError("experiments root must not be a symlink")
    root = raw_root.resolve()
    if root != data_root and data_root not in root.parents:
        raise ReportContractError("experiments root escapes the data directory")
    candidate = root / experiment_id
    if candidate.is_symlink():
        raise ReportContractError("experiment directory must not be a symlink")
    try:
        resolved = _contained(candidate, root, field="experiment directory")
    except OSError as exc:
        raise ReportContractError("experiment directory cannot be resolved") from exc
    if not resolved.is_dir():
        raise ReportContractError("experiment directory does not exist")
    metadata = resolved / "metadata.json"
    if metadata.is_symlink() or not metadata.is_file():
        raise ReportContractError("metadata.json must be a regular file")
    _contained(metadata, resolved, field="metadata.json")
    return resolved


def experiment_lock_name(experiment_id: str) -> str:
    validate_experiment_id(experiment_id)
    digest = hashlib.sha256(experiment_id.encode("utf-8")).hexdigest()
    return f".report-locks/experiment-{digest}.lock"


def _iter_source_files(experiment_root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in experiment_root.rglob("*"):
        relative = path.relative_to(experiment_root)
        if not relative.parts or relative.parts[0] == "reports":
            continue
        if relative.name == "report_state.json":
            continue
        if path.is_symlink():
            raise ReportContractError(f"symlink source is forbidden: {relative}")
        if path.suffix.lower() in ALLOWED_REPORT_INPUT_SUFFIXES:
            candidates.append(path)
    unique = sorted(set(candidates), key=lambda item: item.relative_to(experiment_root).as_posix())
    if len(unique) > MAX_SOURCE_FILES:
        raise ReportContractError("too many report source files")
    return unique


def _regular_source(path: Path, experiment_root: Path) -> tuple[Path, os.stat_result]:
    if path.is_symlink():
        raise ReportContractError(f"symlink source is forbidden: {path.name}")
    resolved = _contained(path, experiment_root, field="report source")
    try:
        info = resolved.stat()
    except OSError as exc:
        raise ReportContractError(f"cannot stat report source: {path.name}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ReportContractError(f"report source is not a regular file: {path.name}")
    if info.st_size > MAX_SOURCE_FILE_BYTES:
        raise ReportContractError(f"report source is too large: {path.name}")
    return resolved, info


def _check_deadline(deadline_epoch: float | None) -> None:
    if deadline_epoch is not None and time.time() >= deadline_epoch:
        raise ReportContractError("report artifact deadline exceeded")


def _hash_file(path: Path, *, deadline_epoch: float | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            _check_deadline(deadline_epoch)
            digest.update(chunk)
    return digest.hexdigest()


def compute_source_fingerprint(
    experiment_root: Path,
    *,
    deadline_epoch: float | None = None,
) -> str:
    """Hash a deterministic, bounded manifest of allowlisted report inputs."""
    experiment_root = Path(experiment_root).resolve()
    digest = hashlib.sha256()
    total = 0
    for path in _iter_source_files(experiment_root):
        _check_deadline(deadline_epoch)
        resolved, info = _regular_source(path, experiment_root)
        total += info.st_size
        if total > MAX_SOURCE_TOTAL_BYTES:
            raise ReportContractError("report sources exceed total size limit")
        record = {
            "path": resolved.relative_to(experiment_root).as_posix(),
            "size": info.st_size,
            "sha256": _hash_file(resolved, deadline_epoch=deadline_epoch),
        }
        digest.update(json.dumps(record, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def _json_text(payload: Mapping[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if len(text.encode("utf-8")) > MAX_JSON_BYTES:
        raise ReportContractError("report JSON exceeds size limit")
    return text


def read_json_object(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    if not path.exists():
        if required:
            raise ReportContractError(f"missing {path.name}")
        return None
    if path.is_symlink() or not path.is_file():
        raise ReportContractError(f"{path.name} must be a regular file")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ReportContractError(f"{path.name} is too large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReportIOError(f"could not read {path.name}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReportContractError(f"invalid {path.name}") from exc
    if not isinstance(payload, dict):
        raise ReportContractError(f"{path.name} must contain a JSON object")
    return payload


def validate_report_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema",
        "experiment_id",
        "source_fingerprint",
        "generation_id",
        "status",
        "attempt_count",
        "max_attempts",
        "not_before",
        "started_at",
        "updated_at",
        "finished_at",
        "owner_token",
        "error_code",
        "error_text",
        "artifacts",
    }
    if set(payload) != required or type(payload.get("schema")) is not int or payload.get("schema") != SCHEMA_VERSION:
        raise ReportContractError("report_state.json has unexpected fields or schema")
    validate_experiment_id(payload.get("experiment_id"))
    validate_generation_id(payload.get("generation_id"))
    validate_generation_id(payload.get("owner_token"))
    fingerprint = payload.get("source_fingerprint")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint):
        raise ReportContractError("invalid source fingerprint")
    if payload.get("status") not in _REPORT_STATUSES:
        raise ReportContractError("invalid report state status")
    attempt_count = payload.get("attempt_count")
    max_attempts = payload.get("max_attempts")
    if type(max_attempts) is not int or not (1 <= max_attempts <= 20):
        raise ReportContractError("invalid max_attempts")
    if type(attempt_count) is not int or not (0 <= attempt_count <= max_attempts):
        raise ReportContractError("invalid attempt_count")
    status = payload["status"]
    if status == "PENDING" and attempt_count != 0:
        raise ReportContractError("PENDING state must have attempt_count zero")
    if status != "PENDING" and attempt_count < 1:
        raise ReportContractError("non-PENDING state must consume an attempt")
    now = time.time()
    times: dict[str, float] = {}
    for field in ("not_before", "started_at", "updated_at"):
        value = payload.get(field)
        if (
            type(value) not in (int, float)
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ReportContractError(f"invalid {field}")
        times[field] = float(value)
    if times["started_at"] > times["updated_at"]:
        raise ReportContractError("report state timestamps are out of order")
    if times["updated_at"] > now + 300:
        raise ReportContractError("report state updated_at is in the future")
    if times["not_before"] > times["updated_at"] + 86_400 + 300:
        raise ReportContractError("report state not_before exceeds bounded backoff")
    finished_at = payload.get("finished_at")
    if status in {"PENDING", "RUNNING"}:
        if finished_at is not None:
            raise ReportContractError("nonterminal state must not have finished_at")
    else:
        if (
            type(finished_at) not in (int, float)
            or not math.isfinite(float(finished_at))
            or not times["started_at"] <= float(finished_at) <= times["updated_at"]
            or float(finished_at) > now + 300
        ):
            raise ReportContractError("invalid finished_at")
    for field in ("error_code", "error_text"):
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > 2_048):
            raise ReportContractError(f"invalid {field}")
    if not isinstance(payload.get("artifacts"), dict):
        raise ReportContractError("artifacts must be an object")
    return dict(payload)


def load_report_state(experiment_root: Path) -> dict[str, Any] | None:
    payload = read_json_object(Path(experiment_root) / "report_state.json", required=False)
    return validate_report_state(payload) if payload is not None else None


def write_report_state(
    experiment_root: Path,
    payload: Mapping[str, Any],
    *,
    expected_owner_token: str | None = None,
    expected_generation_id: str | None = None,
    expected_status: str | None = None,
) -> None:
    root = Path(experiment_root).resolve()
    path = _contained(root / "report_state.json", root, field="report state")
    if path.is_symlink():
        raise ReportContractError("report state must not be a symlink")
    expected = (expected_owner_token, expected_generation_id, expected_status)
    if any(value is not None for value in expected) and not all(value is not None for value in expected):
        raise ReportContractError("persisted state fence requires owner, generation, and status")
    if all(value is not None for value in expected):
        current = load_report_state(root)
        if current is None or (
            current["owner_token"] != expected_owner_token
            or current["generation_id"] != expected_generation_id
            or current["status"] != expected_status
        ):
            raise ReportContractError("persisted report state changed before terminal write")
    atomic_write_text(
        path,
        _json_text(validate_report_state(payload)),
    )


def write_report_state_if_unchanged(
    experiment_root: Path,
    payload: Mapping[str, Any],
    *,
    expected: Mapping[str, Any],
) -> None:
    """Replace exact state while the caller holds the experiment kernel lock.

    The persistent per-experiment lock is the concurrency authority for every
    legitimate report-state writer.  This equality check is an additional
    stale-context fence inside that locked domain; filesystem rename is not a
    portable compare-and-swap against writers that violate the lock contract.
    """
    root = Path(experiment_root).resolve()
    path = _contained(root / "report_state.json", root, field="report state")
    if path.is_symlink():
        raise ReportContractError("report state must not be a symlink")
    validated_expected = validate_report_state(expected)
    validated_payload = validate_report_state(payload)
    current = load_report_state(root)
    if current is None or current != validated_expected:
        raise ReportContractError("persisted report state changed before exact transition")
    atomic_write_text(path, _json_text(validated_payload))


def report_force_context(
    state: Mapping[str, Any],
    current_manifest: Mapping[str, Any] | None,
) -> str:
    """Return an opaque digest binding operator confirmation to exact report truth."""
    validated = validate_report_state(state)
    manifest_generation: str | None = None
    if current_manifest is not None:
        generation = current_manifest.get("generation_id")
        manifest_generation = validate_generation_id(generation)
    identity = {
        "domain": "cryodaq.report-force-context",
        "version": 1,
        "state": {
            "experiment_id": validated["experiment_id"],
            "source_fingerprint": validated["source_fingerprint"],
            "generation_id": validated["generation_id"],
            "owner_token": validated["owner_token"],
            "status": validated["status"],
            "attempt_count": validated["attempt_count"],
            "max_attempts": validated["max_attempts"],
            "updated_at": validated["updated_at"],
        },
        "manifest_generation_id": manifest_generation,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def report_state_summary(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return the bounded, non-secret state subset permitted in force audit records."""
    validated = validate_report_state(state)
    return {
        "generation_id": validated["generation_id"],
        "status": validated["status"],
        "attempt_count": validated["attempt_count"],
        "max_attempts": validated["max_attempts"],
        "updated_at": validated["updated_at"],
        "error_code": (
            str(validated["error_code"])[:128]
            if validated["error_code"] is not None
            else None
        ),
    }


def write_report_force_audit(
    experiment_root: Path,
    audit_id: str,
    *,
    phase: str,
    payload: Mapping[str, Any],
) -> Path:
    """Create one immutable, experiment-local force-retry audit record."""
    audit_id = validate_generation_id(audit_id)
    if phase not in {"before", "after"}:
        raise ReportContractError("force audit phase must be before or after")
    expected = {
        "schema",
        "event",
        "audit_id",
        "at",
        "operator",
        "experiment_id",
        "force_context",
        "before",
        "requested_generation_id",
        "manifest_generation_id",
        "outcome",
        "after",
    }
    record = dict(payload)
    if set(record) != expected or record.get("schema") != 1:
        raise ReportContractError("force audit record has an invalid schema")
    if record.get("audit_id") != audit_id:
        raise ReportContractError("force audit id mismatch")
    validate_experiment_id(record.get("experiment_id"))
    validate_generation_id(record.get("requested_generation_id"))
    manifest_generation = record.get("manifest_generation_id")
    if manifest_generation is not None:
        validate_generation_id(manifest_generation)
    operator = record.get("operator")
    if (
        not isinstance(operator, str)
        or not (1 <= len(operator) <= 128)
        or operator != operator.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in operator)
    ):
        raise ReportContractError("force audit operator is invalid")
    context = record.get("force_context")
    if not isinstance(context, str) or re.fullmatch(r"[0-9a-f]{64}", context) is None:
        raise ReportContractError("force audit context is invalid")
    at = record.get("at")
    if type(at) not in (int, float) or not math.isfinite(float(at)) or float(at) < 0:
        raise ReportContractError("force audit timestamp is invalid")
    before = record.get("before")
    if not isinstance(before, dict) or set(before) != {
        "generation_id",
        "status",
        "attempt_count",
        "max_attempts",
        "updated_at",
        "error_code",
    }:
        raise ReportContractError("force audit before state is invalid")
    validate_generation_id(before.get("generation_id"))
    if before.get("status") not in {"FAILED", "RUNNING"}:
        raise ReportContractError("force audit before status is invalid")
    before_attempt = before.get("attempt_count")
    before_max = before.get("max_attempts")
    if (
        type(before_attempt) is not int
        or type(before_max) is not int
        or not (1 <= before_attempt == before_max <= 20)
    ):
        raise ReportContractError("force audit before attempts are invalid")
    before_updated = before.get("updated_at")
    if (
        type(before_updated) not in (int, float)
        or not math.isfinite(float(before_updated))
        or float(before_updated) < 0
    ):
        raise ReportContractError("force audit before timestamp is invalid")
    before_error = before.get("error_code")
    if before_error is not None and (
        not isinstance(before_error, str) or len(before_error) > 128
    ):
        raise ReportContractError("force audit before error code is invalid")
    if record.get("event") == "report_force_confirmed":
        if phase != "before" or record.get("outcome") != "accepted" or record.get("after") is not None:
            raise ReportContractError("force before audit fields are invalid")
    elif record.get("event") == "report_force_completed":
        if phase != "after" or record.get("outcome") not in {"succeeded", "failed"}:
            raise ReportContractError("force after audit fields are invalid")
        after = record.get("after")
        if not isinstance(after, dict) or set(after) != set(before):
            raise ReportContractError("force audit after state is invalid")
        validate_generation_id(after.get("generation_id"))
        expected_status = "SUCCEEDED" if record.get("outcome") == "succeeded" else "FAILED"
        if after.get("status") != expected_status:
            raise ReportContractError("force audit after status is invalid")
        if type(after.get("attempt_count")) is not int or after.get("attempt_count") != 1:
            raise ReportContractError("force audit after attempt is invalid")
        if type(after.get("max_attempts")) is not int or not (1 <= after["max_attempts"] <= 20):
            raise ReportContractError("force audit after max_attempts is invalid")
        after_updated = after.get("updated_at")
        if (
            type(after_updated) not in (int, float)
            or not math.isfinite(float(after_updated))
            or float(after_updated) < 0
        ):
            raise ReportContractError("force audit after timestamp is invalid")
        after_error = after.get("error_code")
        if after_error is not None and (
            not isinstance(after_error, str) or len(after_error) > 128
        ):
            raise ReportContractError("force audit after error code is invalid")
    else:
        raise ReportContractError("force audit event is invalid")
    text = _json_text(record)

    root = Path(experiment_root)
    if root.is_symlink() or not root.is_dir():
        raise ReportContractError("experiment root must be a real directory")
    resolved_root = root.resolve()
    reports = resolved_root / "reports"
    audit = reports / "audit"
    force_dir = audit / "report_force"
    for directory, field in (
        (reports, "reports directory"),
        (audit, "report audit directory"),
        (force_dir, "report force audit directory"),
    ):
        if directory.is_symlink():
            raise ReportContractError(f"{field} must not be a symlink")
        directory.mkdir(exist_ok=True)
        if not directory.is_dir() or directory.resolve() != directory:
            raise ReportContractError(f"{field} must be a real directory")
        _contained(directory, resolved_root, field=field)
    target = force_dir / f"{audit_id}.{phase}.json"
    if os.path.lexists(target):
        raise ReportContractError("force audit record already exists")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(target, flags, 0o600)
        try:
            remaining = memoryview(text.encode("utf-8"))
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    raise OSError("short force audit write")
                remaining = remaining[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise ReportIOError("force audit record could not be persisted") from exc
    _fsync_dir(force_dir)
    return target


def new_pending_state(
    experiment_id: str,
    source_fingerprint: str,
    generation_id: str,
    owner_token: str,
    *,
    max_attempts: int = 5,
    not_before: float | None = None,
) -> dict[str, Any]:
    """Create durable automatic work without claiming the child lock."""
    now = time.time()
    return validate_report_state(
        {
            "schema": SCHEMA_VERSION,
            "experiment_id": experiment_id,
            "source_fingerprint": source_fingerprint,
            "generation_id": generation_id,
            "status": "PENDING",
            "attempt_count": 0,
            "max_attempts": max_attempts,
            "not_before": now if not_before is None else not_before,
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "owner_token": owner_token,
            "error_code": None,
            "error_text": "",
            "artifacts": {},
        }
    )


def new_running_state(
    experiment_id: str,
    source_fingerprint: str,
    generation_id: str,
    owner_token: str,
    *,
    attempt_count: int,
    max_attempts: int = 5,
) -> dict[str, Any]:
    now = time.time()
    return validate_report_state(
        {
            "schema": SCHEMA_VERSION,
            "experiment_id": experiment_id,
            "source_fingerprint": source_fingerprint,
            "generation_id": generation_id,
            "status": "RUNNING",
            "attempt_count": attempt_count,
            "max_attempts": max_attempts,
            "not_before": now,
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "owner_token": owner_token,
            "error_code": None,
            "error_text": "",
            "artifacts": {},
        }
    )


def terminal_state(
    running: Mapping[str, Any],
    *,
    owner_token: str,
    succeeded: bool,
    artifacts: Mapping[str, Any] | None = None,
    error_code: str | None = None,
    error_text: str = "",
) -> dict[str, Any]:
    current = validate_report_state(running)
    if current["owner_token"] != owner_token:
        raise ReportContractError("stale owner token cannot update report state")
    now = time.time()
    current.update(
        status="SUCCEEDED" if succeeded else "FAILED",
        updated_at=now,
        finished_at=now,
        artifacts=dict(artifacts or {}),
        error_code=error_code,
        error_text=error_text[:2_048],
    )
    return validate_report_state(current)


def _artifact_records(
    staging: Path,
    *,
    deadline_epoch: float | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    total = 0
    for path in sorted(staging.rglob("*")):
        _check_deadline(deadline_epoch)
        if path.is_symlink():
            raise ReportContractError("generation artifacts must not be symlinks")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ReportContractError("generation artifact must be a regular file")
        if path.suffix.lower() not in ALLOWED_REPORT_INPUT_SUFFIXES:
            raise ReportContractError("generation artifact has an unsupported extension")
        size = path.stat().st_size
        if size > MAX_GENERATED_FILE_BYTES:
            raise ReportContractError(f"generation artifact is too large: {path.name}")
        total += size
        if total > MAX_GENERATED_TOTAL_BYTES:
            raise ReportContractError("generated artifacts exceed total size limit")
        if len(records) >= MAX_GENERATED_FILES:
            raise ReportContractError("too many generated artifacts")
        records.append(
            {
                "path": path.relative_to(staging).as_posix(),
                "size": size,
                "sha256": _hash_file(path, deadline_epoch=deadline_epoch),
            }
        )
    return records


def build_current_manifest(
    experiment_root: Path,
    *,
    generation_id: str,
    source_fingerprint: str,
    sections: Sequence[str],
    skipped: bool,
    reason: str,
    deadline_epoch: float | None = None,
) -> dict[str, Any]:
    generation_id = validate_generation_id(generation_id)
    paths = resolve_report_paths(experiment_root)
    raw_staging = paths.staging_root / generation_id
    _reject_symlink_components(
        raw_staging,
        paths.experiment_root,
        field="generation staging directory",
    )
    staging = _contained(
        raw_staging,
        paths.experiment_root,
        field="generation staging directory",
    )
    if not staging.is_dir() or staging.is_symlink():
        raise ReportContractError("generation staging directory is missing or unsafe")
    raw_generation = paths.generations_root / generation_id
    _reject_symlink_components(
        raw_generation,
        paths.experiment_root,
        field="generation directory",
    )
    _contained(
        raw_generation,
        paths.experiment_root,
        field="generation directory",
    )
    docx = staging / "report_editable.docx"
    assets = staging / "assets"
    if not skipped:
        if docx.is_symlink() or not docx.is_file():
            raise ReportContractError("enabled report DOCX must be a regular file")
        if assets.is_symlink() or not assets.is_dir():
            raise ReportContractError("enabled report assets must be a real directory")
    prefix = Path("reports") / "generations" / generation_id
    payload = {
        "schema": SCHEMA_VERSION,
        "experiment_id": Path(experiment_root).name,
        "generation_id": generation_id,
        "source_fingerprint": source_fingerprint,
        "created_at": time.time(),
        "report": {
            "docx_path": (prefix / "report_editable.docx").as_posix(),
            "pdf_path": ((prefix / "report_raw.pdf").as_posix() if (staging / "report_raw.pdf").is_file() else None),
            "assets_dir": (prefix / "assets").as_posix(),
            "sections": list(sections),
            "skipped": bool(skipped),
            "reason": str(reason)[:2_048],
        },
        "artifacts": _artifact_records(staging, deadline_epoch=deadline_epoch),
    }
    validate_current_manifest(payload, Path(experiment_root), require_artifacts=False)
    return payload


def validate_current_manifest(
    payload: Mapping[str, Any],
    experiment_root: Path,
    *,
    require_artifacts: bool = True,
) -> dict[str, Any]:
    expected = {
        "schema",
        "experiment_id",
        "generation_id",
        "source_fingerprint",
        "created_at",
        "report",
        "artifacts",
    }
    if set(payload) != expected or type(payload.get("schema")) is not int or payload.get("schema") != SCHEMA_VERSION:
        raise ReportContractError("invalid current report manifest schema")
    if payload.get("experiment_id") != Path(experiment_root).name:
        raise ReportContractError("manifest experiment mismatch")
    generation_id = validate_generation_id(payload.get("generation_id"))
    fingerprint = payload.get("source_fingerprint")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint):
        raise ReportContractError("invalid manifest fingerprint")
    created_at = payload.get("created_at")
    if type(created_at) not in (int, float) or not math.isfinite(float(created_at)):
        raise ReportContractError("invalid manifest timestamp")
    report = payload.get("report")
    report_fields = {"docx_path", "pdf_path", "assets_dir", "sections", "skipped", "reason"}
    if not isinstance(report, dict) or set(report) != report_fields:
        raise ReportContractError("invalid manifest report object")
    if not isinstance(report["sections"], list) or not all(
        isinstance(item, str) and len(item) <= 128 for item in report["sections"]
    ):
        raise ReportContractError("invalid manifest sections")
    if type(report["skipped"]) is not bool or not isinstance(report["reason"], str):
        raise ReportContractError("invalid manifest report status")
    paths = resolve_report_paths(experiment_root)
    raw_generation = paths.generations_root / generation_id
    _reject_symlink_components(
        raw_generation,
        paths.experiment_root,
        field="generation directory",
    )
    generation_root = _contained(
        raw_generation,
        paths.experiment_root,
        field="generation directory",
    )
    if require_artifacts and (generation_root.is_symlink() or not generation_root.is_dir()):
        raise ReportContractError("generation directory is missing or unsafe")
    for field in ("docx_path", "assets_dir"):
        value = report[field]
        if not isinstance(value, str):
            raise ReportContractError(f"invalid {field}")
        raw_candidate = paths.experiment_root / value
        _reject_symlink_components(raw_candidate, paths.experiment_root, field=field)
        candidate = _contained(raw_candidate, generation_root, field=field)
        _contained(candidate, paths.experiment_root, field=field)
        if require_artifacts and not report["skipped"]:
            if field == "docx_path" and (candidate.is_symlink() or not candidate.is_file()):
                raise ReportContractError("manifest DOCX is missing or unsafe")
            if field == "assets_dir" and (candidate.is_symlink() or not candidate.is_dir()):
                raise ReportContractError("manifest assets directory is missing or unsafe")
    if report["pdf_path"] is not None:
        if not isinstance(report["pdf_path"], str):
            raise ReportContractError("invalid pdf_path")
        raw_pdf = paths.experiment_root / report["pdf_path"]
        _reject_symlink_components(raw_pdf, paths.experiment_root, field="pdf_path")
        pdf = _contained(raw_pdf, generation_root, field="pdf_path")
        _contained(pdf, paths.experiment_root, field="pdf_path")
        if require_artifacts and (pdf.is_symlink() or not pdf.is_file()):
            raise ReportContractError("manifest PDF is missing")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) > MAX_SOURCE_FILES:
        raise ReportContractError("invalid artifact manifest")
    total = 0
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {"path", "size", "sha256"}:
            raise ReportContractError("invalid artifact record")
        relative = artifact["path"]
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ReportContractError("invalid artifact path")
        raw_artifact = generation_root / relative
        _reject_symlink_components(raw_artifact, generation_root, field="artifact")
        candidate = _contained(raw_artifact, generation_root, field="artifact")
        if type(artifact["size"]) is not int or artifact["size"] < 0:
            raise ReportContractError("invalid artifact size")
        if artifact["size"] > MAX_GENERATED_FILE_BYTES:
            raise ReportContractError("manifest artifact is too large")
        total += artifact["size"]
        if total > MAX_GENERATED_TOTAL_BYTES:
            raise ReportContractError("manifest artifacts exceed total size limit")
        if not isinstance(artifact["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]):
            raise ReportContractError("invalid artifact hash")
        if require_artifacts:
            if not candidate.is_file() or candidate.is_symlink():
                raise ReportContractError("manifest artifact is missing or unsafe")
            if candidate.stat().st_size != artifact["size"] or _hash_file(candidate) != artifact["sha256"]:
                raise ReportContractError("manifest artifact hash/size mismatch")
    return dict(payload)


def load_current_manifest(experiment_root: Path) -> dict[str, Any] | None:
    paths = resolve_report_paths(experiment_root)
    payload = read_json_object(paths.current_manifest, required=False)
    return (
        validate_current_manifest(payload, Path(experiment_root), require_artifacts=True)
        if payload is not None
        else None
    )


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _fsync_generation(path: Path, *, deadline_epoch: float | None = None) -> None:
    """Flush generation file contents and directories before pointer publication."""
    directories = [path]
    for item in sorted(path.rglob("*")):
        _check_deadline(deadline_epoch)
        if item.is_symlink():
            raise ReportContractError("generation artifacts must not be symlinks")
        if item.is_dir():
            directories.append(item)
            continue
        if not item.is_file():
            raise ReportContractError("generation artifact must be a regular file")
        with item.open("rb") as stream:
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass
    for directory in reversed(directories):
        _fsync_dir(directory)


def promote_generation(
    experiment_root: Path,
    generation_id: str,
    manifest: Mapping[str, Any],
    *,
    hook: Callable[[str], None] | None = None,
    deadline_epoch: float | None = None,
) -> Path:
    """Promote one complete generation, then atomically select it last."""
    generation_id = validate_generation_id(generation_id)
    paths = resolve_report_paths(experiment_root, create_generations=True)
    experiment_root = paths.experiment_root
    raw_staging = paths.staging_root / generation_id
    raw_final = paths.generations_root / generation_id
    _reject_symlink_components(
        raw_staging,
        experiment_root,
        field="generation staging directory",
    )
    _reject_symlink_components(
        raw_final,
        experiment_root,
        field="generation directory",
    )
    staging = _contained(
        raw_staging,
        experiment_root,
        field="generation staging directory",
    )
    final = _contained(
        raw_final,
        experiment_root,
        field="generation directory",
    )
    if not staging.is_dir() or staging.is_symlink() or final.exists():
        raise ReportContractError("generation staging/final path is invalid")
    validated = validate_current_manifest(manifest, experiment_root, require_artifacts=False)
    _artifact_records(staging, deadline_epoch=deadline_epoch)
    _fsync_generation(staging, deadline_epoch=deadline_epoch)
    if hook:
        hook("after_render")
    os.replace(staging, final)
    _fsync_dir(final)
    _fsync_dir(final.parent)
    validate_current_manifest(validated, experiment_root, require_artifacts=True)
    if hook:
        hook("after_promote")
    atomic_write_text(paths.current_manifest, _json_text(validated))
    _fsync_dir(paths.reports)
    if hook:
        hook("after_manifest")
    return final
