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

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ReplayExperimentStub:
    """Lightweight metadata-only experiment manager for replay mode."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir / "experiments"
        self._active: dict[str, Any] | None = None
        self._phases: list[dict[str, Any]] = []

    @property
    def active_experiment(self) -> dict[str, Any] | None:
        return dict(self._active) if self._active else None

    @property
    def phases(self) -> list[dict[str, Any]]:
        return [dict(p) for p in self._phases]

    @property
    def current_phase(self) -> str | None:
        return self._active.get("phase") if self._active else None

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
        if custom_fields:
            self._active["custom_fields"] = dict(custom_fields)
        self._persist()
        logger.info("ReplayExperimentStub created: %s ('%s')", exp_id, title)
        return dict(self._active)

    def advance_phase(
        self,
        phase: str,
        operator: str = "operator",
        *,
        expected_experiment_id: str,
    ) -> dict[str, Any]:
        if self._active is None:
            raise RuntimeError("No active replay experiment")
        if type(expected_experiment_id) is not str or expected_experiment_id != self._active["experiment_id"]:
            raise RuntimeError("Replay experiment identity mismatch")
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
        return dict(self._active)

    def _persist(self) -> None:
        if self._active is None:
            return
        exp_dir = self._data_dir / self._active["experiment_id"]
        exp_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            **self._active,
            "phases": list(self._phases),
        }
        (exp_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
