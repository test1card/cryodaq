"""Durable append-only storage for thermal-conductivity autosweeps.

Rows and authority records deliberately share one file. A data row is not
accepted until a following checkpoint has also been flushed and fsynced. The
terminal record is authoritative when present. Before a terminal exists, the
longest unambiguous contiguous checkpoint prefix is recoverable RUNNING data.
"""

from __future__ import annotations

import csv
import json
import math
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from cryodaq.channels.descriptors import ChannelDescriptorV1, ChannelQuantity
from cryodaq.channels.persistence import (
    PersistedChannelEnvelopeError,
    PersistedChannelEnvelopeV1,
    decode_persisted_channel_envelope,
)

SCHEMA_VERSION = 1
_COMMENT_PREFIX = "# "
_COLUMNS = (
    "timestamp_utc",
    "P_W",
    "T_hot_K",
    "T_cold_K",
    "T_avg_K",
    "dT_K",
    "R_KW",
    "G_WK",
    "settled_pct",
)
_TERMINAL_STATUSES = frozenset({"COMPLETED", "ABORTED", "FAILED"})


class ConductivityRunFormatError(ValueError):
    """The durable autosweep artifact contradicts its authority records."""


@dataclass(frozen=True, slots=True)
class ConductivityRunSnapshot:
    """Validated durable or legacy reader result."""

    rows: tuple[dict[str, float], ...]
    raw_row_count: int
    run_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    parameters: dict[str, Any]
    status: str
    accepted_point_count: int
    checkpoint_count: int
    recovery_required: bool
    binding_recorded: bool
    bound_experiment_id: str | None
    terminal: dict[str, Any] | None
    durable_format: bool


@dataclass(frozen=True, slots=True)
class ConductivityDescriptorBinding:
    """Verified immutable measurement-source identity for one autosweep."""

    power: ChannelDescriptorV1
    temperatures: tuple[ChannelDescriptorV1, ...]


def _descriptor_envelope_payload(descriptor: ChannelDescriptorV1) -> dict[str, Any]:
    envelope = PersistedChannelEnvelopeV1.from_descriptor(descriptor)
    payload = json.loads(envelope.canonical_json)
    assert isinstance(payload, dict)
    return payload


def build_conductivity_descriptor_parameters(
    *,
    power: ChannelDescriptorV1,
    temperatures: tuple[ChannelDescriptorV1, ...],
) -> dict[str, Any]:
    """Build the self-validating descriptor portion of autosweep parameters."""

    payload = {
        "power_channel": power.channel_id,
        "temperature_channels": [descriptor.channel_id for descriptor in temperatures],
        "bound_descriptors": {
            "power": _descriptor_envelope_payload(power),
            "temperatures": [_descriptor_envelope_payload(descriptor) for descriptor in temperatures],
        },
    }
    validate_conductivity_descriptor_parameters(payload)
    return payload


def _decode_descriptor_payload(payload: object) -> ChannelDescriptorV1:
    if type(payload) is not dict:
        raise ConductivityRunFormatError("Autosweep descriptor envelope must be an object.")
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        envelope = decode_persisted_channel_envelope(encoded)
    except (TypeError, ValueError, PersistedChannelEnvelopeError) as exc:
        raise ConductivityRunFormatError(f"Autosweep descriptor envelope is invalid: {exc}") from exc
    if encoded != envelope.canonical_json:
        raise ConductivityRunFormatError("Autosweep descriptor envelope is not canonical.")
    return envelope.descriptor


def validate_conductivity_descriptor_parameters(parameters: object) -> ConductivityDescriptorBinding:
    """Validate exact power/temperature identities carried by a durable run."""

    if type(parameters) is not dict:
        raise ConductivityRunFormatError("Autosweep parameters must be an object.")
    bound = parameters.get("bound_descriptors")
    if type(bound) is not dict or set(bound) != {"power", "temperatures"}:
        raise ConductivityRunFormatError("Autosweep bound_descriptors schema is invalid.")
    temperature_payloads = bound["temperatures"]
    if type(temperature_payloads) is not list or len(temperature_payloads) < 2:
        raise ConductivityRunFormatError("Autosweep requires at least two bound temperature descriptors.")
    power = _decode_descriptor_payload(bound["power"])
    temperatures = tuple(_decode_descriptor_payload(payload) for payload in temperature_payloads)
    if power.quantity is not ChannelQuantity.POWER:
        raise ConductivityRunFormatError("Autosweep power descriptor quantity is not power.")
    if any(descriptor.quantity is not ChannelQuantity.TEMPERATURE for descriptor in temperatures):
        raise ConductivityRunFormatError("Autosweep temperature descriptor quantity is not temperature.")
    temperature_ids = [descriptor.channel_id for descriptor in temperatures]
    if len(set(temperature_ids)) != len(temperature_ids):
        raise ConductivityRunFormatError("Autosweep temperature descriptor identity is duplicated.")
    if power.channel_id in temperature_ids:
        raise ConductivityRunFormatError("Autosweep power and temperature descriptor identities overlap.")
    if parameters.get("power_channel") != power.channel_id:
        raise ConductivityRunFormatError("Autosweep power channel does not match its descriptor.")
    if parameters.get("temperature_channels") != temperature_ids:
        raise ConductivityRunFormatError("Autosweep temperature channels do not match their descriptors.")
    return ConductivityDescriptorBinding(power=power, temperatures=temperatures)


def _utc_text(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat()


def _durable_started_at(value: object) -> datetime:
    if type(value) is not str or not value:
        raise ConductivityRunFormatError("Autosweep start started_at is invalid.")
    text = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ConductivityRunFormatError("Autosweep start started_at is invalid.") from exc
    if parsed.tzinfo is None:
        raise ConductivityRunFormatError("Autosweep start started_at must include a timezone.")
    return parsed.astimezone(UTC)


def _durable_finished_at(value: object, *, started_at: datetime) -> datetime:
    if type(value) is not str or not value:
        raise ConductivityRunFormatError("Autosweep terminal finished_at is invalid.")
    text = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ConductivityRunFormatError("Autosweep terminal finished_at is invalid.") from exc
    if parsed.tzinfo is None:
        raise ConductivityRunFormatError("Autosweep terminal finished_at must include a timezone.")
    finished_at = parsed.astimezone(UTC)
    if finished_at < started_at:
        raise ConductivityRunFormatError("Autosweep terminal finished_at precedes started_at.")
    return finished_at


def _json_comment(payload: dict[str, Any]) -> str:
    return _COMMENT_PREFIX + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _validated_point(point: dict[str, Any]) -> dict[str, float | str]:
    timestamp = str(point.get("timestamp_utc") or _utc_text()).strip()
    numeric: dict[str, float] = {}
    for name in _COLUMNS[1:]:
        try:
            value = float(point[name])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Autosweep point requires numeric {name}.") from exc
        if not math.isfinite(value):
            raise ValueError(f"Autosweep point {name} must be finite.")
        numeric[name] = value
    return {"timestamp_utc": timestamp, **numeric}


def _fsync_directory(path: Path) -> None:
    """Persist one directory namespace on POSIX; Windows has no dir-fsync API."""

    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError(f"Not a directory: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_durable_directory(path: Path) -> None:
    """Create missing components and fsync every newly changed parent."""

    missing: list[Path] = []
    candidate = path
    while not candidate.exists():
        missing.append(candidate)
        if candidate.parent == candidate:
            break
        candidate = candidate.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=False)
        _fsync_directory(directory.parent)


class ConductivityRunWriter:
    """One-writer append-only autosweep artifact."""

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        started_at: datetime,
        parameters: dict[str, Any],
    ) -> None:
        self.path = Path(path)
        self.run_id = str(run_id).strip()
        if not self.run_id:
            raise ValueError("run_id is required.")
        self.started_at = started_at
        self.parameters = dict(parameters)
        self.accepted_point_count = 0
        self._terminal_written = False
        self._binding_written = False
        self._point_append_started = False
        _ensure_durable_directory(self.path.parent)
        self._handle: TextIO = self.path.open("x", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(self._handle, fieldnames=list(_COLUMNS), lineterminator="\n")
        try:
            self._handle.write(
                _json_comment(
                    {
                        "record_type": "conductivity_run_start",
                        "schema_version": SCHEMA_VERSION,
                        "run_id": self.run_id,
                        "started_at": _utc_text(started_at),
                        "parameters": self.parameters,
                    }
                )
            )
            self._writer.writeheader()
            self._sync()
            _fsync_directory(self.path.parent)
        except BaseException:
            self._handle.close()
            raise

    def _sync(self) -> None:
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def append_binding(self, experiment_id: str | None) -> dict[str, Any]:
        """Persist exact experiment identity, or explicit absence, before arming."""

        if self._terminal_written:
            raise RuntimeError("Cannot bind after the terminal record.")
        if self._point_append_started:
            raise RuntimeError("Cannot bind after a point append has started.")
        if self._binding_written:
            raise RuntimeError("Experiment binding already written.")
        normalized = None if experiment_id is None else str(experiment_id).strip()
        if experiment_id is not None and not normalized:
            raise ValueError("experiment_id must be non-empty when provided.")
        binding = {
            "record_type": "conductivity_run_binding",
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "experiment_id": normalized,
            "bound_at": _utc_text(),
        }
        self._binding_written = True
        self._handle.write(_json_comment(binding))
        self._sync()
        return binding

    def append_point(self, point: dict[str, Any]) -> int:
        """Durably accept one point, returning the new accepted count."""

        if self._terminal_written:
            raise RuntimeError("Cannot append a point after the terminal record.")
        row = _validated_point(point)
        self._point_append_started = True
        self._writer.writerow(row)
        self._sync()
        next_count = self.accepted_point_count + 1
        self._handle.write(
            _json_comment(
                {
                    "record_type": "conductivity_run_checkpoint",
                    "schema_version": SCHEMA_VERSION,
                    "run_id": self.run_id,
                    "accepted_point_count": next_count,
                    "checkpointed_at": _utc_text(),
                }
            )
        )
        self._sync()
        self.accepted_point_count = next_count
        return next_count

    def append_terminal(
        self,
        status: str,
        *,
        finished_at: datetime,
        error: str | None = None,
        trailing_write_outcome: str | None = None,
    ) -> dict[str, Any]:
        """Append and fsync the sole terminal authority, then close the file."""

        normalized = str(status).strip().upper()
        if normalized not in _TERMINAL_STATUSES:
            raise ValueError(f"Unsupported autosweep terminal status: {status!r}")
        if self._terminal_written:
            raise RuntimeError("Terminal record already written.")
        if trailing_write_outcome is not None and (normalized != "FAILED" or trailing_write_outcome != "indeterminate"):
            raise ValueError("Only FAILED may declare trailing_write_outcome=indeterminate.")
        terminal: dict[str, Any] = {
            "record_type": "conductivity_run_terminal",
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": normalized,
            "accepted_point_count": self.accepted_point_count,
            "finished_at": _utc_text(finished_at),
        }
        if error:
            terminal["error"] = str(error)
        if trailing_write_outcome is not None:
            terminal["trailing_write_outcome"] = trailing_write_outcome
        self._handle.write("\n" + _json_comment(terminal))
        self._sync()
        self._terminal_written = True
        self._handle.close()
        return terminal

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.close()


def _parse_rows(lines: list[str]) -> tuple[list[str], list[dict[str, float] | None], list[int]]:
    data_entries = [(line_number, line) for line_number, line in enumerate(lines) if line and not line.startswith("#")]
    if not data_entries:
        return [], [], []
    data_lines = [line for _, line in data_entries]
    reader = csv.DictReader(data_lines)
    rows: list[dict[str, float] | None] = []
    row_positions = [line_number for line_number, _ in data_entries[1:]]
    numeric_fields = _COLUMNS[1:] if tuple(reader.fieldnames or ()) == _COLUMNS else ("T_avg_K", "G_WK", "R_KW")
    for item in reader:
        try:
            numeric = {name: float(item.get(name, "")) for name in numeric_fields}
            row = {
                "temperature_k": numeric["T_avg_K"],
                "conductance_wk": numeric["G_WK"],
                "resistance_kw": numeric["R_KW"],
            }
        except (TypeError, ValueError):
            rows.append(None)
            continue
        rows.append(row if all(math.isfinite(value) for value in numeric.values()) else None)
    return list(reader.fieldnames or []), rows, row_positions


def _contiguous_checkpoint_count(
    checkpoints: list[dict[str, Any]],
    *,
    run_id: str,
    parsed_rows: list[dict[str, float] | None],
    row_positions: list[int],
    metadata_positions: dict[int, int],
) -> int:
    expected = 1
    for item in checkpoints:
        if item.get("schema_version") != SCHEMA_VERSION or item.get("run_id") != run_id:
            break
        count = item.get("accepted_point_count")
        if type(count) is not int or count != expected:
            break
        if count > len(parsed_rows) or parsed_rows[count - 1] is None:
            break
        checkpoint_position = metadata_positions[id(item)]
        if checkpoint_position <= row_positions[count - 1]:
            break
        if count < len(row_positions) and checkpoint_position >= row_positions[count]:
            break
        expected += 1
    return expected - 1


def read_conductivity_run(path: Path) -> ConductivityRunSnapshot:
    """Read legacy CSV or the validated durable autosweep prefix."""

    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    metadata: list[dict[str, Any]] = []
    metadata_positions: dict[int, int] = {}
    for line_number, line in enumerate(lines):
        if not line.startswith(_COMMENT_PREFIX):
            continue
        try:
            candidate = json.loads(line[len(_COMMENT_PREFIX) :])
        except ValueError:
            continue
        if isinstance(candidate, dict):
            metadata.append(candidate)
            metadata_positions[id(candidate)] = line_number
    starts = [item for item in metadata if item.get("record_type") == "conductivity_run_start"]
    fieldnames, parsed_rows, row_positions = _parse_rows(lines)
    if not starts:
        if tuple(fieldnames) == _COLUMNS:
            raise ConductivityRunFormatError("Durable autosweep header has no start authority.")
        legacy_rows = tuple(row for row in parsed_rows if row is not None)
        return ConductivityRunSnapshot(
            rows=legacy_rows,
            raw_row_count=len(parsed_rows),
            run_id=None,
            started_at=None,
            finished_at=None,
            parameters={},
            status="LEGACY",
            accepted_point_count=len(legacy_rows),
            checkpoint_count=0,
            recovery_required=False,
            binding_recorded=False,
            bound_experiment_id=None,
            terminal=None,
            durable_format=False,
        )
    if len(starts) != 1 or starts[0].get("schema_version") != SCHEMA_VERSION:
        raise ConductivityRunFormatError("Autosweep start authority is missing or ambiguous.")
    if tuple(fieldnames) != _COLUMNS:
        raise ConductivityRunFormatError("Autosweep CSV header does not match its schema.")
    run_id = starts[0].get("run_id")
    if type(run_id) is not str or not run_id.strip():
        raise ConductivityRunFormatError("Autosweep start run_id is invalid.")
    started_at = _durable_started_at(starts[0].get("started_at"))
    parameters = starts[0].get("parameters")
    if type(parameters) is not dict:
        raise ConductivityRunFormatError("Autosweep start parameters are invalid.")
    checkpoints = [item for item in metadata if item.get("record_type") == "conductivity_run_checkpoint"]
    contiguous = _contiguous_checkpoint_count(
        checkpoints,
        run_id=run_id,
        parsed_rows=parsed_rows,
        row_positions=row_positions,
        metadata_positions=metadata_positions,
    )
    bindings = [item for item in metadata if item.get("record_type") == "conductivity_run_binding"]
    if len(bindings) > 1:
        raise ConductivityRunFormatError("Autosweep experiment binding is ambiguous.")
    bound_experiment_id: str | None = None
    if bindings:
        binding = bindings[0]
        binding_position = metadata_positions[id(binding)]
        start_position = metadata_positions[id(starts[0])]
        effect_positions = [
            *row_positions,
            *(metadata_positions[id(item)] for item in checkpoints),
            *(
                metadata_positions[id(item)]
                for item in metadata
                if item.get("record_type") == "conductivity_run_terminal"
            ),
        ]
        if binding_position <= start_position or (effect_positions and binding_position >= min(effect_positions)):
            raise ConductivityRunFormatError("Autosweep experiment binding must precede every point effect.")
        if binding.get("schema_version") != SCHEMA_VERSION or binding.get("run_id") != run_id:
            raise ConductivityRunFormatError("Autosweep experiment binding does not match its start record.")
        candidate = binding.get("experiment_id")
        if candidate is not None and (type(candidate) is not str or not candidate.strip()):
            raise ConductivityRunFormatError("Autosweep experiment binding is invalid.")
        bound_experiment_id = candidate
    terminals = [item for item in metadata if item.get("record_type") == "conductivity_run_terminal"]
    if not terminals:
        published = tuple(row for row in parsed_rows[:contiguous] if row is not None)
        return ConductivityRunSnapshot(
            rows=published,
            raw_row_count=len(parsed_rows),
            run_id=run_id,
            started_at=started_at,
            finished_at=None,
            parameters=dict(parameters),
            status="RUNNING",
            accepted_point_count=contiguous,
            checkpoint_count=contiguous,
            recovery_required=True,
            binding_recorded=bool(bindings),
            bound_experiment_id=bound_experiment_id,
            terminal=None,
            durable_format=True,
        )
    if len(terminals) != 1:
        raise ConductivityRunFormatError("Autosweep terminal authority is ambiguous.")
    terminal = terminals[0]
    if terminal.get("schema_version") != SCHEMA_VERSION or terminal.get("run_id") != run_id:
        raise ConductivityRunFormatError("Autosweep terminal authority does not match its start record.")
    status = str(terminal.get("status", "")).upper()
    if status not in _TERMINAL_STATUSES:
        raise ConductivityRunFormatError("Autosweep terminal status is invalid.")
    finished_at = _durable_finished_at(terminal.get("finished_at"), started_at=started_at)
    accepted = terminal.get("accepted_point_count")
    if type(accepted) is not int or accepted < 0 or accepted > len(parsed_rows):
        raise ConductivityRunFormatError("Autosweep terminal accepted_point_count is invalid.")
    accepted_rows = parsed_rows[:accepted]
    if any(row is None for row in accepted_rows):
        raise ConductivityRunFormatError("Autosweep accepted prefix contains an invalid row.")
    if contiguous < accepted:
        raise ConductivityRunFormatError("Autosweep terminal claims a row without its durable checkpoint.")
    trailing = len(parsed_rows) - accepted
    if status in {"COMPLETED", "ABORTED"} and trailing:
        raise ConductivityRunFormatError(f"{status} autosweep has unaccepted trailing rows.")
    if status == "FAILED" and (
        trailing > 1 or (trailing == 1 and terminal.get("trailing_write_outcome") != "indeterminate")
    ):
        raise ConductivityRunFormatError("FAILED autosweep trailing row authority is invalid.")
    terminal_position = metadata_positions[id(terminal)]
    last_row_position = max(row_positions, default=-1)
    last_checkpoint_position = max((metadata_positions[id(item)] for item in checkpoints), default=-1)
    if terminal_position <= max(last_row_position, last_checkpoint_position):
        raise ConductivityRunFormatError("Autosweep terminal authority does not follow all row/checkpoint effects.")

    published_rows = tuple(row for row in accepted_rows if row is not None)
    return ConductivityRunSnapshot(
        rows=published_rows,
        raw_row_count=len(parsed_rows),
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        parameters=dict(parameters),
        status=status,
        accepted_point_count=accepted,
        checkpoint_count=contiguous,
        recovery_required=False,
        binding_recorded=bool(bindings),
        bound_experiment_id=bound_experiment_id,
        terminal=terminal,
        durable_format=True,
    )


def recover_conductivity_run_after_verified_off(
    path: Path,
    *,
    finished_at: datetime,
) -> ConductivityRunSnapshot:
    """Terminalize one restart-orphaned durable prefix after external OFF proof.

    The caller owns the verified-OFF decision. This function owns only the
    append-only artifact reconciliation and refuses legacy, unbound, replaced,
    or structurally inconsistent files.
    """

    target = Path(path)
    expected_identity = target.stat()
    snapshot = read_conductivity_run(target)
    if not snapshot.durable_format or snapshot.run_id is None or snapshot.started_at is None:
        raise ConductivityRunFormatError("Only a durable autosweep can be recovered.")
    if not snapshot.binding_recorded or snapshot.bound_experiment_id is None:
        raise ConductivityRunFormatError("A restart autosweep recovery requires a durable experiment binding.")
    if snapshot.terminal is not None:
        return snapshot
    terminal_time = finished_at.astimezone(UTC) if finished_at.tzinfo is not None else finished_at.replace(tzinfo=UTC)
    if terminal_time < snapshot.started_at:
        raise ConductivityRunFormatError("Autosweep recovery finished_at precedes started_at.")
    trailing = snapshot.raw_row_count - snapshot.accepted_point_count
    if trailing not in {0, 1}:
        raise ConductivityRunFormatError("Autosweep recovery has ambiguous trailing rows.")
    status = "FAILED" if trailing else "ABORTED"
    terminal: dict[str, Any] = {
        "record_type": "conductivity_run_terminal",
        "schema_version": SCHEMA_VERSION,
        "run_id": snapshot.run_id,
        "status": status,
        "accepted_point_count": snapshot.accepted_point_count,
        "finished_at": _utc_text(terminal_time),
        "error": "recovered_after_restart",
    }
    if trailing:
        terminal["trailing_write_outcome"] = "indeterminate"
    with target.open("r+", encoding="utf-8", newline="") as handle:
        if not os.path.samestat(expected_identity, os.fstat(handle.fileno())):
            raise ConductivityRunFormatError("Autosweep artifact identity changed during recovery.")
        handle.seek(0, os.SEEK_END)
        handle.write("\n" + _json_comment(terminal))
        handle.flush()
        os.fsync(handle.fileno())
    recovered = read_conductivity_run(target)
    if recovered.terminal != terminal:
        raise ConductivityRunFormatError("Autosweep terminal recovery did not verify after append.")
    return recovered
