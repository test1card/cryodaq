"""Context assembler for GemmaAgent LLM prompts.

Each task type (alarm summary, diagnostic, campaign report) requires
different context. Builders read SQLite state and format compact text
for LLM token budget.

Cycle 1: AlarmContext dataclass + build_alarm_context interface.
SQLite queries and full context assembly wired in Cycle 2.
Slice B (diagnostic) and Slice C (campaign) contexts deferred.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AlarmContext:
    """Context for alarm summary generation (Slice A)."""

    alarm_id: str
    level: str
    channels: list[str]
    values: dict[str, float]
    phase: str | None
    experiment_id: str | None
    experiment_age_s: float | None
    target_temp: float | None
    active_interlocks: list[str] = field(default_factory=list)
    recent_readings_text: str = ""
    recent_alarms_text: str = ""


class ContextBuilder:
    """Assembles engine state for LLM prompt construction."""

    def __init__(self, sqlite_reader: Any, experiment_manager: Any) -> None:
        self._reader = sqlite_reader
        self._em = experiment_manager

    async def build_alarm_context(
        self,
        alarm_payload: dict[str, Any],
        *,
        lookback_s: float = 60.0,
        recent_alarm_lookback_s: float = 3600.0,
    ) -> AlarmContext:
        """Assemble context for a Slice A alarm summary prompt.

        Reads experiment state from ExperimentManager (in-memory, fast).
        SQLite reading history and alarm history wired in Cycle 2.
        """
        alarm_id = alarm_payload.get("alarm_id", "unknown")
        channels: list[str] = alarm_payload.get("channels", [])
        values: dict[str, float] = alarm_payload.get("values", {})
        level: str = alarm_payload.get("level", "WARNING")

        experiment_id: str | None = getattr(self._em, "active_experiment_id", None)

        phase: str | None = None
        if hasattr(self._em, "get_current_phase"):
            try:
                phase = self._em.get_current_phase()
            except Exception:
                pass

        experiment_age_s: float | None = _compute_experiment_age(self._em)

        return AlarmContext(
            alarm_id=alarm_id,
            level=level,
            channels=channels,
            values=values,
            phase=phase,
            experiment_id=experiment_id,
            experiment_age_s=experiment_age_s,
            target_temp=None,
            active_interlocks=[],
            recent_readings_text=_readings_stub(channels, lookback_s),
            recent_alarms_text=_alarms_stub(recent_alarm_lookback_s),
        )


def _compute_experiment_age(em: Any) -> float | None:
    try:
        history = em.get_phase_history()
        if not history:
            return None
        first = history[0].get("started_at")
        if not first:
            return None
        from datetime import UTC, datetime

        started = datetime.fromisoformat(first)
        return (datetime.now(UTC) - started.astimezone(UTC)).total_seconds()
    except Exception:
        return None


def _readings_stub(channels: list[str], lookback_s: float) -> str:
    ch = ", ".join(channels) if channels else "(none)"
    return f"[Readings for {ch} over last {lookback_s:.0f}s — wired in Cycle 2]"


def _alarms_stub(lookback_s: float) -> str:
    return f"[Alarm history over last {lookback_s:.0f}s — wired in Cycle 2]"
