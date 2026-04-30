"""Context assembler for GemmaAgent LLM prompts.

Each task type (alarm summary, diagnostic, campaign report) requires
different context. Builders read SQLite state and format compact text
for LLM token budget.

Cycle 1: AlarmContext dataclass + build_alarm_context interface.
Cycle 3: ExperimentFinalizeContext, SensorAnomalyContext, ShiftHandoverContext added.
Cycle 4: DiagnosticSuggestionContext + real SQLite channel history reads.
Slice C (campaign) contexts deferred.
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
        SQLite reading history and alarm history wired in Cycle 4 — historical SQLite context.
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

    async def build_experiment_finalize_context(
        self, payload: dict[str, Any]
    ) -> ExperimentFinalizeContext:
        """Assemble context for experiment finalize/stop/abort prompt."""
        return _build_experiment_finalize_context(self._em, payload)

    async def build_sensor_anomaly_context(
        self, payload: dict[str, Any]
    ) -> SensorAnomalyContext:
        """Assemble context for sensor anomaly analysis prompt."""
        return _build_sensor_anomaly_context(self._em, payload)

    async def build_shift_handover_context(
        self, payload: dict[str, Any]
    ) -> ShiftHandoverContext:
        """Assemble context for shift handover summary prompt."""
        return _build_shift_handover_context(self._em, payload)

    async def build_periodic_report_context(
        self,
        *,
        window_minutes: int = 60,
    ) -> PeriodicReportContext:
        """Aggregate engine activity over last window_minutes for periodic report.

        Uses get_operator_log() with time window — no new SQLite methods needed.
        All event types (alarms, phases, experiments, operator entries) are
        stored in the operator log with identifying tags.
        """
        now = datetime.now(UTC)
        start_time = now - timedelta(minutes=window_minutes)

        entries: list[Any] = []
        _ctx_failed = False
        if hasattr(self._reader, "get_operator_log"):
            try:
                entries = await self._reader.get_operator_log(
                    start_time=start_time,
                    end_time=now,
                    limit=50,
                )
            except Exception:
                logger.warning(
                    "PeriodicReportContext: get_operator_log failed — window data unavailable",
                    exc_info=True,
                )
                _ctx_failed = True

        alarm_entries = [e for e in entries if "alarm" in e.tags]
        phase_entries = [e for e in entries if "phase_transition" in e.tags or "phase" in e.tags]
        experiment_entries = [e for e in entries if "experiment" in e.tags]
        calibration_entries = [e for e in entries if "calibration" in e.tags]
        # Exclude machine-generated and AI-generated entries from operator section
        operator_entries = [
            e for e in entries
            if e.source != "auto" and "ai" not in e.tags and "auto" not in e.tags
        ]
        # Any auto event not classified above (calibration, leak_rate, etc.)
        other_entries = [
            e for e in entries
            if "auto" in e.tags
            and "alarm" not in e.tags
            and "phase_transition" not in e.tags
            and "phase" not in e.tags
            and "experiment" not in e.tags
            and "calibration" not in e.tags
            and "ai" not in e.tags
        ]

        total_event_count = (
            len(alarm_entries) + len(phase_entries) + len(experiment_entries)
            + len(calibration_entries) + len(operator_entries) + len(other_entries)
        )

        experiment_id: str | None = getattr(self._em, "active_experiment_id", None)
        phase: str | None = None
        if hasattr(self._em, "get_current_phase"):
            try:
                phase = self._em.get_current_phase()
            except Exception:
                pass

        return PeriodicReportContext(
            window_minutes=window_minutes,
            active_experiment_id=experiment_id,
            active_experiment_phase=phase,
            alarm_entries=alarm_entries,
            phase_entries=phase_entries,
            experiment_entries=experiment_entries,
            calibration_entries=calibration_entries,
            operator_entries=operator_entries,
            other_entries=other_entries,
            total_event_count=total_event_count,
            context_read_failed=_ctx_failed,
        )

    async def build_diagnostic_suggestion_context(
        self,
        alarm_payload: dict[str, Any],
        *,
        lookback_min: int = 60,
    ) -> DiagnosticSuggestionContext:
        """Assemble context for Slice B diagnostic suggestion.

        Reads last lookback_min minutes of readings for alarm channels
        from SQLite. Alarm history, cooldown history, and pressure trend
        remain stubs until Cycle 4.1 wires those sources.
        """
        alarm_id = alarm_payload.get("alarm_id", "unknown")
        channels: list[str] = alarm_payload.get("channels", [])
        values: dict[str, float] = alarm_payload.get("values", {})
        channel_history = await self._read_channel_history(channels, lookback_min)
        pressure_trend = await self._read_pressure_trend()
        return DiagnosticSuggestionContext(
            alarm_id=alarm_id,
            channels=channels,
            values=values,
            channel_history=channel_history,
            recent_alarms="нет данных",
            past_cooldowns="нет истории",
            pressure_trend=pressure_trend,
            lookback_min=lookback_min,
        )

    async def _read_channel_history(self, channels: list[str], lookback_min: int) -> str:
        """Read recent readings for alarm channels from SQLite."""
        if not channels or not hasattr(self._reader, "read_readings_history"):
            return "нет данных"
        try:
            from_ts = _time.time() - lookback_min * 60
            data: dict[str, list[tuple[float, float]]] = (
                await self._reader.read_readings_history(
                    channels=channels,
                    from_ts=from_ts,
                    limit_per_channel=20,
                )
            )
            if not data:
                return "нет данных"
            lines: list[str] = []
            for ch, readings in data.items():
                if readings:
                    vals = [f"{v:.4g}" for _, v in readings[-5:]]
                    lines.append(f"- {ch}: [{', '.join(vals)}]")
            return "\n".join(lines) if lines else "нет данных"
        except Exception:
            logger.debug("ContextBuilder: channel history read failed", exc_info=True)
            return "нет данных"

    async def _read_pressure_trend(self) -> str:
        """Read recent pressure readings from SQLite."""
        if not hasattr(self._reader, "read_readings_history"):
            return "нет данных"
        try:
            from_ts = _time.time() - 30 * 60
            data: dict[str, list[tuple[float, float]]] = (
                await self._reader.read_readings_history(
                    from_ts=from_ts,
                    limit_per_channel=10,
                )
            )
            pressure = {
                k: v
                for k, v in data.items()
                if "pressure" in k.lower() or "mbar" in k.lower()
            }
            if not pressure:
                return "нет данных"
            lines: list[str] = []
            for ch, readings in pressure.items():
                if len(readings) >= 2:
                    start = readings[0][1]
                    end = readings[-1][1]
                    threshold = 0.01 * max(abs(start), 1e-12)
                    arrow = "→" if abs(end - start) < threshold else ("↑" if end > start else "↓")
                    lines.append(f"- {ch}: {start:.2e} → {end:.2e} {arrow}")
            return "\n".join(lines) if lines else "нет данных"
        except Exception:
            logger.debug("ContextBuilder: pressure trend read failed", exc_info=True)
            return "нет данных"


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


def _readings_stub(_channels: list[str], _lookback_s: float) -> str:
    return "нет данных"


def _alarms_stub(_lookback_s: float) -> str:
    return "нет данных"


# ---------------------------------------------------------------------------
# Experiment finalize context
# ---------------------------------------------------------------------------


@dataclass
class ExperimentFinalizeContext:
    """Context for experiment finalize/stop/abort summary (Slice A)."""

    experiment_id: str | None
    name: str
    action: str
    duration_str: str
    phases_text: str
    alarms_summary_text: str


# ---------------------------------------------------------------------------
# Sensor anomaly context
# ---------------------------------------------------------------------------


@dataclass
class SensorAnomalyContext:
    """Context for sensor anomaly analysis (Slice A)."""

    alarm_id: str
    level: str
    channel: str
    channels: list[str]
    values: dict[str, float]
    message: str
    health_score: str
    fault_flags: str
    current_value: str
    experiment_id: str | None
    phase: str | None


# ---------------------------------------------------------------------------
# Shift handover context
# ---------------------------------------------------------------------------


@dataclass
class ShiftHandoverContext:
    """Context for shift handover summary (Slice A)."""

    experiment_id: str | None
    phase: str | None
    experiment_age: str
    active_alarms: str
    recent_events: str
    shift_duration_h: int


# ---------------------------------------------------------------------------
# Concrete build methods on ContextBuilder
# ---------------------------------------------------------------------------


def _build_experiment_finalize_context(
    em: Any, payload: dict[str, Any]
) -> ExperimentFinalizeContext:
    action = payload.get("action", "experiment_finalize")
    experiment = payload.get("experiment", {})
    experiment_id = experiment.get("experiment_id")
    name = experiment.get("name") or experiment.get("title") or "—"
    age_float = _compute_experiment_age(em)
    if age_float is None:
        # Fallback: try to compute from experiment dict
        started = experiment.get("started_at") or experiment.get("created_at")
        if started:
            try:
                from datetime import UTC, datetime

                start_dt = datetime.fromisoformat(started)
                age_s = (datetime.now(UTC) - start_dt.astimezone(UTC)).total_seconds()
                duration_str = _format_age(age_s)
            except Exception:
                duration_str = "—"
        else:
            duration_str = "—"
    else:
        duration_str = _format_age(age_float)
    phases = experiment.get("phases") or experiment.get("phase_history") or []
    if phases:
        phases_text = "\n".join(
            f"- {p.get('phase', '?')}: {p.get('started_at', '?')}" for p in phases
        )
    else:
        phases_text = "нет данных"
    return ExperimentFinalizeContext(
        experiment_id=experiment_id,
        name=name,
        action=action,
        duration_str=duration_str,
        phases_text=phases_text,
        alarms_summary_text="нет данных",
    )


def _build_sensor_anomaly_context(
    em: Any, payload: dict[str, Any]
) -> SensorAnomalyContext:
    alarm_id = payload.get("alarm_id", "unknown")
    level = payload.get("level", "CRITICAL")
    channels: list[str] = payload.get("channels", [])
    values: dict[str, float] = payload.get("values", {})
    message = payload.get("message", "—")
    channel = channels[0] if channels else alarm_id.replace("diag:", "")
    current_value = "—"
    if values:
        first_ch = next(iter(values))
        current_value = f"{values[first_ch]:.4g}"
    experiment_id: str | None = getattr(em, "active_experiment_id", None)
    phase: str | None = None
    if hasattr(em, "get_current_phase"):
        try:
            phase = em.get_current_phase()
        except Exception:
            pass
    health_score = payload.get("health_score", "—")
    fault_flags_raw = payload.get("fault_flags", [])
    fault_flags = ", ".join(fault_flags_raw) if fault_flags_raw else "—"
    return SensorAnomalyContext(
        alarm_id=alarm_id,
        level=level,
        channel=channel,
        channels=channels,
        values=values,
        message=message,
        health_score=str(health_score),
        fault_flags=fault_flags,
        current_value=current_value,
        experiment_id=experiment_id,
        phase=phase,
    )


# ---------------------------------------------------------------------------
# Campaign report context (Slice C) — async path for future event-driven use
# ---------------------------------------------------------------------------


@dataclass
class CampaignReportContext:
    """Context for Slice C campaign report intro (async EventBus path)."""

    experiment_id: str | None
    name: str
    duration_str: str
    phases_text: str
    channel_stats: str
    alarms_summary: str
    operator_notes: str


# ---------------------------------------------------------------------------
# Diagnostic suggestion context (Slice B)
# ---------------------------------------------------------------------------


@dataclass
class DiagnosticSuggestionContext:
    """Context for diagnostic suggestion generation (Slice B)."""

    alarm_id: str
    channels: list[str]
    values: dict[str, float]
    channel_history: str
    recent_alarms: str
    past_cooldowns: str
    pressure_trend: str
    lookback_min: int = 60


def _build_shift_handover_context(em: Any, payload: dict[str, Any]) -> ShiftHandoverContext:
    experiment_id: str | None = getattr(em, "active_experiment_id", None)
    phase: str | None = None
    if hasattr(em, "get_current_phase"):
        try:
            phase = em.get_current_phase()
        except Exception:
            pass
    age_s = _compute_experiment_age(em)
    experiment_age = _format_age(age_s) if age_s is not None else "—"
    shift_duration_h = int(payload.get("shift_duration_h", 8))
    return ShiftHandoverContext(
        experiment_id=experiment_id,
        phase=phase,
        experiment_age=experiment_age,
        active_alarms="нет данных",
        recent_events="нет данных",
        shift_duration_h=shift_duration_h,
    )


def _format_age(age_s: float) -> str:
    h, rem = divmod(int(age_s), 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}ч {m}м"
    if m > 0:
        return f"{m}м {s}с"
    return f"{s}с"


# ---------------------------------------------------------------------------
# Periodic report context (F29)
# ---------------------------------------------------------------------------


@dataclass
class PeriodicReportContext:
    """Context for periodic narrative report (F29)."""

    window_minutes: int
    active_experiment_id: str | None
    active_experiment_phase: str | None
    alarm_entries: list[Any] = field(default_factory=list)
    phase_entries: list[Any] = field(default_factory=list)
    experiment_entries: list[Any] = field(default_factory=list)
    calibration_entries: list[Any] = field(default_factory=list)
    operator_entries: list[Any] = field(default_factory=list)
    other_entries: list[Any] = field(default_factory=list)
    total_event_count: int = 0
    context_read_failed: bool = False

    def to_template_dict(self) -> dict[str, str]:
        """Format all context fields as prompt-ready strings."""
        if self.active_experiment_id:
            phase_str = (
                f" (фаза: {self.active_experiment_phase})"
                if self.active_experiment_phase else ""
            )
            active_exp = f"{self.active_experiment_id}{phase_str}"
        else:
            active_exp = "нет активного эксперимента"

        return {
            "active_experiment_summary": active_exp,
            "events_section": _format_log_entries(self.other_entries) or "(нет)",
            "alarms_section": _format_log_entries(self.alarm_entries) or "(нет)",
            "phase_transitions_section": _format_log_entries(self.phase_entries) or "(нет)",
            "operator_entries_section": _format_log_entries(self.operator_entries) or "(нет)",
            "calibration_section": _format_log_entries(self.calibration_entries) or "(нет)",
            "total_event_count": str(self.total_event_count),
        }


def _format_log_entries(entries: list[Any]) -> str:
    if not entries:
        return ""
    lines = []
    for e in entries[:10]:
        ts = e.timestamp.astimezone().strftime("%H:%M") if hasattr(e, "timestamp") else "?"
        msg = getattr(e, "message", str(e))[:120]
        lines.append(f"- {ts}: {msg}")
    return "\n".join(lines)
