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
    """Context for alarm summary generation (Slice A).

    F-BotPolish: ``values`` is now ``dict[str, Any]`` so the builder can
    pre-format numeric readings (1-decimal Kelvin, 2-sig-fig scientific
    pressure) before the prompt template strings them. Existing tests
    that pass raw floats keep working — strings flow through ``str(v)``
    in templates the same way floats do.
    """

    alarm_id: str
    level: str
    channels: list[str]
    values: dict[str, Any]
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
        raw_values: dict[str, Any] = alarm_payload.get("values", {})
        level: str = alarm_payload.get("level", "WARNING")

        experiment_id: str | None = getattr(self._em, "active_experiment_id", None)

        phase: str | None = None
        if hasattr(self._em, "get_current_phase"):
            try:
                phase = self._em.get_current_phase()
            except Exception:
                pass

        experiment_age_s: float | None = _compute_experiment_age(self._em)

        # F-BotPolish: format raw values once at the seam (1-decimal Kelvin,
        # 2-sig-fig scientific pressure) and surface implausibility hints in
        # `recent_readings_text` so Gemma frames sensor faults as faults.
        formatted_values = _format_values_dict(raw_values)
        anomaly_text = _build_anomaly_hint_text(raw_values)
        recent_readings_text = anomaly_text or _readings_stub(channels, lookback_s)

        return AlarmContext(
            alarm_id=alarm_id,
            level=level,
            channels=channels,
            values=formatted_values,
            phase=phase,
            experiment_id=experiment_id,
            experiment_age_s=experiment_age_s,
            target_temp=None,
            active_interlocks=[],
            recent_readings_text=recent_readings_text,
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
# F-BotPolish — value formatting + implausibility sanity hints.
# ---------------------------------------------------------------------------

# Cryogenic temperature channel ids in this codebase always start with the
# Cyrillic "Т" (U+0422); the Latin "T" path is kept defensively because
# legacy / external payloads may use the ASCII letter.
_CRYO_PREFIXES: tuple[str, ...] = ("Т", "T")
# Hard physical limits for cryogenic-stage thermometers. Above ~500 K the
# sensor is broken; below 0 K is unphysical and indicates a wiring fault.
_TEMP_IMPLAUSIBLE_HIGH_K: float = 500.0
_TEMP_IMPLAUSIBLE_LOW_K: float = -50.0


def _is_cryo_channel(channel: str) -> bool:
    return any(channel.startswith(prefix) for prefix in _CRYO_PREFIXES)


def _is_pressure_channel(channel: str) -> bool:
    """Heuristic: name-based pressure-channel detection.

    Cycle-2 fix for Codex finding on commit 53981a1: relying on numeric
    magnitude alone meant ``P_main = 1e-3`` rendered as ``"0.00"`` and
    ``5e-3`` as ``"0.01"``. Pressure channels in this codebase are named
    via ``MV…`` / ``V<N>`` (Thyracont VSP63D), ``P_…`` (engine adapters),
    or ``…/pressure`` (broker routing) and report unit "мбар"/"mbar".
    """
    if not channel:
        return False
    cl = channel.lower()
    return (
        "pressure" in cl
        or "/mbar" in cl
        or cl.startswith("p_")
        or cl.startswith("p/")
        or cl.startswith("mv")
        or cl.startswith("v1")
        or cl.startswith("v2")
        or cl.startswith("v3")
    )


def _format_value_for_prompt(value: Any, channel: str = "", unit: str = "") -> str:
    """Render a numeric reading for an LLM prompt in compact form.

    Without this rounding, ``str({"Т1": 4.347123456789})`` leaks 12-digit
    decimals into the Gemma prompt, which yields confused alarm summaries.

    Detection order:
    - pressure channels (by name OR unit "мбар"/"mbar") → 2-sig-fig scientific.
    - cryogenic temperature channels (Т*/T*) → 1 decimal place.
    - magnitude band (|v| < 1e-3 or |v| > 1e6) → 2-sig-fig scientific
      (defensive fallback when channel id is unknown).
    - everything else → 2 decimals.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    unit_l = unit.lower() if unit else ""
    if _is_pressure_channel(channel) or unit_l in {"мбар", "mbar"}:
        return f"{v:.2e}"
    if _is_cryo_channel(channel):
        return f"{v:.1f}"
    if abs(v) < 1e-3 or abs(v) > 1e6:
        return f"{v:.2e}"
    return f"{v:.2f}"


def _format_values_dict(values: dict[str, Any]) -> dict[str, str]:
    return {ch: _format_value_for_prompt(v, ch) for ch, v in values.items()}


def _detect_implausible(channel: str, value: Any, unit: str = "K") -> str | None:
    """Return a short Russian hint when ``value`` is physically impossible.

    Cryogenic temperature sensors should report a cold-stage temperature in
    the few-Kelvin to a few-hundred-Kelvin band. Anything outside that band
    is sensor failure, not an experiment alarm to interpret literally; the
    hint helps the LLM frame the response correctly instead of suggesting
    the operator "проверить температуру".
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if _is_cryo_channel(channel) and unit == "K":
        if v > _TEMP_IMPLAUSIBLE_HIGH_K:
            return (
                "физически невозможно для криогенного канала, "
                "вероятно сбой сенсора"
            )
        if v < _TEMP_IMPLAUSIBLE_LOW_K:
            return "отрицательное значение, физически невозможно"
    return None


def _build_anomaly_hint_text(values: dict[str, Any]) -> str:
    """Compose a multi-line `recent_readings_text` carrying anomaly hints.

    Empty if no implausible values; otherwise lines of the form:
    ``Т1: 948.0 K — физически невозможно для криогенного канала, …``.
    """
    lines: list[str] = []
    for ch, val in values.items():
        hint = _detect_implausible(ch, val)
        if hint is None:
            continue
        formatted = _format_value_for_prompt(val, ch)
        lines.append(f"{ch}: {formatted} K — {hint}")
    return "\n".join(lines)


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
