"""F-ReplayPhases (v0.55.9): minimal experiment manager for replay mode.

Writes ``metadata.json`` in the same format the live ``ExperimentManager``
expects but without scheduler / safety / report-generation infrastructure.
Replay-created experiments are flagged ``is_replay: true`` so the UI can
filter them out of production analytics if desired (architect intent: the
replay-driven experiments are demo / training artifacts, not real
measurements).

Architectural notes:
- Lives entirely in the replay-engine subprocess; no live engine state is
  touched.
- Persists to ``data/experiments/<id>/metadata.json`` (same root as the live
  ExperimentManager) so the existing archive UI can render replay
  experiments alongside real ones — operator can opt into hiding them via
  a future "Скрыть replay-эксперименты" filter.
- Single-active-experiment invariant matches the live manager: a second
  ``create_retroactive()`` while one is active raises ``RuntimeError``.
- Phase transitions append a closed-phase record to ``self._phases`` and
  set ``active.phase`` + ``active.phase_started_at`` for the new one.
"""

from __future__ import annotations

import copy
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryodaq.core.phase_labels import PHASE_ORDER

logger = logging.getLogger(__name__)

REPLAY_METADATA_SCHEMA = 1
_REPLAY_REQUIRED_FIELDS = frozenset(
    {
        "experiment_id",
        "title",
        "sample",
        "operator",
        "status",
        "start_time",
        "end_time",
        "description",
        "notes",
        "is_replay",
        "phase",
        "phase_started_at",
        "custom_fields",
    }
)


class ReplayExperimentStub:
    """Lightweight metadata-only experiment manager for replay mode."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir / "experiments"
        self._active: dict[str, Any] | None = None
        self._phases: list[dict[str, Any]] = []
        self._reload_error: str | None = None
        self._reload_active()

    @property
    def active_experiment(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._active) if self._active else None

    @property
    def phases(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._phases)

    @property
    def current_phase(self) -> str | None:
        return self._active.get("phase") if self._active else None

    @property
    def phase_started_at(self) -> str | None:
        """Exact transition instant for the currently active phase."""
        return self._active.get("phase_started_at") if self._active else None

    @property
    def availability_error(self) -> str | None:
        """Reason replay experiment authority is unavailable, if any."""
        return self._reload_error

    def _require_available(self) -> None:
        if self._reload_error is not None:
            raise RuntimeError(self._reload_error)

    def create_retroactive(
        self,
        *,
        title: str,
        sample: str,
        operator: str,
        start_time: str,
        description: str = "",
        notes: str = "",
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_available()
        if self._active is not None:
            raise RuntimeError("Experiment already active in replay session — finalize first")
        exp_id = uuid.uuid4().hex[:12]
        exp_dir = self._data_dir / exp_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        self._active = {
            "experiment_id": exp_id,
            "title": title,
            "sample": sample,
            "operator": operator,
            "status": "active",
            "start_time": start_time,
            "end_time": None,
            "description": description,
            "notes": notes,
            "is_replay": True,
            "phase": "preparation",
            "phase_started_at": datetime.now(UTC).isoformat(),
        }
        self._phases = []
        self._active["custom_fields"] = copy.deepcopy(custom_fields or {})
        self._persist()
        logger.info("ReplayExperimentStub created: %s ('%s')", exp_id, title)
        return copy.deepcopy(self._active)

    def advance_phase(
        self,
        phase: str,
        operator: str = "operator",
        *,
        expected_experiment_id: str,
    ) -> dict[str, Any]:
        self._require_available()
        if self._active is None:
            raise RuntimeError("No active replay experiment")
        if type(expected_experiment_id) is not str or expected_experiment_id != self._active["experiment_id"]:
            raise RuntimeError("Replay experiment identity mismatch")
        if type(phase) is not str or phase not in PHASE_ORDER:
            raise ValueError(f"Unknown replay phase: {phase!r}")
        now_iso = datetime.now(UTC).isoformat()
        previous_phase = self._active.get("phase")
        if previous_phase:
            self._phases.append(
                {
                    "phase": previous_phase,
                    "started_at": self._active.get("phase_started_at", now_iso),
                    "ended_at": now_iso,
                    "operator": operator,
                }
            )
        self._active["phase"] = phase
        self._active["phase_started_at"] = now_iso
        self._persist()
        logger.info("ReplayExperimentStub phase: %s → %s", previous_phase, phase)
        return copy.deepcopy(self._active)

    def _persist(self) -> None:
        if self._active is None:
            return
        exp_dir = self._data_dir / self._active["experiment_id"]
        exp_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "schema": REPLAY_METADATA_SCHEMA,
            **self._active,
            "phases": copy.deepcopy(self._phases),
        }
        (exp_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _reload_active(self) -> None:
        """Restore one explicitly-authoritative active replay record, if valid."""
        if not self._data_dir.exists():
            return

        def reject_active(metadata_path: Path, reason: str) -> None:
            self._reload_error = f"invalid active replay metadata: {reason}"
            logger.error(
                "Replay startup unavailable for %s: %s",
                metadata_path,
                self._reload_error,
            )

        candidates: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for metadata_path in self._data_dir.glob("*/metadata.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if not isinstance(metadata, dict):
                    continue
                if metadata.get("is_replay") is not True or metadata.get("status") != "active":
                    continue
                if metadata.get("schema") != REPLAY_METADATA_SCHEMA:
                    reject_active(metadata_path, "unsupported schema")
                    return
                if set(metadata) - (_REPLAY_REQUIRED_FIELDS | {"schema", "phases"}):
                    reject_active(metadata_path, "unexpected fields")
                    return
                if set(metadata) & _REPLAY_REQUIRED_FIELDS != _REPLAY_REQUIRED_FIELDS:
                    reject_active(metadata_path, "required fields missing")
                    return
                experiment_id = metadata.get("experiment_id")
                if not isinstance(experiment_id, str) or not experiment_id:
                    reject_active(metadata_path, "invalid experiment identity")
                    return
                if metadata_path.parent.name != experiment_id:
                    reject_active(metadata_path, "directory identity mismatch")
                    return
                required_string_fields = (
                    "title",
                    "sample",
                    "operator",
                    "start_time",
                    "description",
                    "notes",
                    "phase",
                    "phase_started_at",
                )
                if not all(isinstance(metadata.get(key), str) for key in required_string_fields):
                    reject_active(metadata_path, "invalid string field")
                    return
                if metadata.get("end_time") is not None and not isinstance(metadata.get("end_time"), str):
                    reject_active(metadata_path, "invalid end time")
                    return
                if metadata.get("phase") not in PHASE_ORDER:
                    reject_active(metadata_path, "invalid phase")
                    return
                if not isinstance(metadata.get("custom_fields"), dict):
                    reject_active(metadata_path, "invalid custom fields")
                    return
                phases = metadata.get("phases", [])
                if not isinstance(phases, list) or not all(isinstance(item, dict) for item in phases):
                    reject_active(metadata_path, "invalid phase history")
                    return
                if not all(
                    isinstance(item.get("phase"), str)
                    and item.get("phase") in PHASE_ORDER
                    and isinstance(item.get("started_at"), str)
                    and isinstance(item.get("ended_at"), str)
                    and isinstance(item.get("operator"), str)
                    for item in phases
                ):
                    reject_active(metadata_path, "invalid phase transition")
                    return
                candidates.append((copy.deepcopy(metadata), copy.deepcopy(phases)))
            except (OSError, ValueError, TypeError):
                logger.warning("Ignoring unreadable replay metadata: %s", metadata_path)
        if len(candidates) > 1:
            self._reload_error = "ambiguous active replay experiments"
            logger.error("Replay startup unavailable: %s", self._reload_error)
            return
        if candidates:
            metadata, phases = candidates[0]
            metadata.pop("schema", None)
            metadata.pop("phases", None)
            self._active = metadata
            self._phases = phases
