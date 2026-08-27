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
    status: str
    accepted_point_count: int
    checkpoint_count: int
    recovery_required: bool
    binding_recorded: bool
    bound_experiment_id: str | None
    terminal: dict[str, Any] | None
    durable_format: bool


def _utc_text(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat()


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
    for item in reader:
        try:
            row = {
                "temperature_k": float(item.get("T_avg_K", "")),
                "conductance_wk": float(item.get("G_WK", "")),
                "resistance_kw": float(item.get("R_KW", "")),
            }
        except (TypeError, ValueError):
            rows.append(None)
            continue
        rows.append(row if all(math.isfinite(value) for value in row.values()) else None)
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
        except json.JSONDecodeError:
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
            legacy_rows, len(parsed_rows), None, "LEGACY", len(legacy_rows), 0, False, False, None, None, False
        )
    if len(starts) != 1 or starts[0].get("schema_version") != SCHEMA_VERSION:
        raise ConductivityRunFormatError("Autosweep start authority is missing or ambiguous.")
    if tuple(fieldnames) != _COLUMNS:
        raise ConductivityRunFormatError("Autosweep CSV header does not match its schema.")
    run_id = starts[0].get("run_id")
    if type(run_id) is not str or not run_id.strip():
        raise ConductivityRunFormatError("Autosweep start run_id is invalid.")
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
            published,
            len(parsed_rows),
            run_id,
            "RUNNING",
            contiguous,
            contiguous,
            True,
            bool(bindings),
            bound_experiment_id,
            None,
            True,
        )
    if len(terminals) != 1:
        raise ConductivityRunFormatError("Autosweep terminal authority is ambiguous.")
    terminal = terminals[0]
    if terminal.get("schema_version") != SCHEMA_VERSION or terminal.get("run_id") != run_id:
        raise ConductivityRunFormatError("Autosweep terminal authority does not match its start record.")
    status = str(terminal.get("status", "")).upper()
    if status not in _TERMINAL_STATUSES:
        raise ConductivityRunFormatError("Autosweep terminal status is invalid.")
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
        published_rows,
        len(parsed_rows),
        run_id,
        status,
        accepted,
        contiguous,
        False,
        bool(bindings),
        bound_experiment_id,
        terminal,
        True,
    )
