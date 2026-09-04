"""Счётчик молекул: кажущийся запас газа в камере (оценка по P и T).

Pressure alone misleads during a cooldown. On 2026-09-03 the gauge fell from
0.0758 to 0.0523 mbar over ten hours and looked like steady progress. It was
not: every live sensor also fell to 0.70 of its starting temperature, and once
the gas temperature is divided out the chamber turns out to have been *gaining*
molecules from hour one — 80.4% at h=1, back to 106.6% by h=9. The pump was
losing to outgassing the whole time and nothing on the stand said so.

This plugin makes that quantity visible, continuously, and says nothing about
what to do with it.

    Ideal gas at one temperature:   N ∝ P / T
    Relative to a baseline:         N/N₀ = (P/P₀) · (T₀/T)

Что это НЕ. Величина — «кажущийся» (apparent) запас газа: давление, делённое на
СРЕДНЕЕ АРИФМЕТИЧЕСКОЕ температур выбранных оператором датчиков. Это среднее не
является объёмно-взвешенной эффективной температурой газа, а VSP63D — Pirani,
откалиброванный по N₂. Поэтому:

* это НЕ буквальный счёт молекул, а температурно-скорректированный
  Pirani-эквивалентный прокси;
* НЕТ гарантии, что истинное значение не ниже показанного. Однозонная модель
  даёт 96.3% на h=7 03.09, правдоподобные доли холодного объёма — 111–124%;
  это разброс модели, а не доказанная нижняя граница;
* меняющийся состав газа смещает и МАСШТАБ, и потенциально НАПРАВЛЕНИЕ тренда,
  выведенного из показаний Pirani. Прежняя формулировка «направление всегда
  верно» снята как недоказанная.
* Датчики выбирает оператор. Какие каналы представляют объём газа — вопрос
  конкретной сборки, а не свойство стенда.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric
from cryodaq.core.channel_identity import matches_channel_id
from cryodaq.core.reading_freshness import judge_freshness
from cryodaq.drivers.base import ChannelStatus, Reading

# Same reasoning as ThermalCalculator._INPUT_WINDOW_S: a derived quantity built
# from several inputs is corrupted, not merely aged, by one stale input. Passed
# explicitly; changes no other caller's default.
_INPUT_WINDOW_S = 30.0

# Below this a temperature reading is not physics. The stand emits -8.888e+88 as
# a "no reading" sentinel and it IS persisted, so a plain finite check is not
# enough. Matches the sensor_fault floor in alarms_v3.yaml.
_MIN_PHYSICAL_K = 1.0

# Window for the rate readout. Long enough that gauge noise does not dominate,
# short enough to show a change of regime within the hour.
_RATE_WINDOW_S = 1800.0

# A slope needs a baseline in TIME, not just a count of points. Fitting five
# samples that arrived inside one second gives an astronomically large and
# entirely meaningless gradient — a replay of the 2026-09-03 database through
# this plugin printed -105 096 647 %/h from exactly that. Real acquisition
# cannot produce it at a 60 s cadence, but a burst, a replay or a backfill can,
# and a readout that can print nonsense under any input is not an instrument.
# Five minutes is the shortest span over which this quantity moves detectably.
_MIN_RATE_SPAN_S = 300.0

# A silent interval is a discontinuity even though nothing was appended to
# record it. When an input is missing or unusable the plugin returns without
# emitting, so the history simply has no point for that time — and the next good
# sample sits next to the previous one looking perfectly contiguous. Fitting
# across that hole bridges an outage of arbitrary length. Any inter-sample gap
# beyond this breaks the trailing run.
_MAX_SAMPLE_GAP_S = 300.0

# Which phases re-zero the counter, and what 100% then means to the operator.
# Phases absent here (preparation, teardown) leave a good baseline alone: an
# unknown or irrelevant phase is not a reason to discard a measurement in
# progress.
_PHASE_BASELINE_LABELS = {
    "vacuum": "начало откачки",
    "cooldown": "начало захолаживания",
    "measurement": "начало измерения",
    "warmup": "начало отогрева",
}

_log = logging.getLogger(__name__)


class MolecularCounter(AnalyticsPlugin):
    """Относительное количество газа в камере, N/N₀, с поправкой на температуру.

    Конфигурация (YAML):
        pressure_channel:  Канал давления (мбар).
        bulk_sensors:      Список ID каналов, представляющих объём газа.
                           НЕ задан по умолчанию — выбор оператора.
        update_interval_s: Как часто публиковать (по умолчанию 60 с).

    Публикует метрику ``gas_inventory`` в процентах от базовой линии.
    """

    def __init__(self, plugin_id: str = "molecular_counter") -> None:
        super().__init__(plugin_id)
        self._pressure_channel: str = ""
        self._bulk_sensors: list[str] = []
        self._update_interval_s: float = 60.0

        # Latest value per input, keyed by the configured ID.
        self._last: dict[str, tuple[float, float]] = {}  # id -> (value, ts)
        self._runtime_label: dict[str, str] = {}

        self._baseline: tuple[float, float, float] | None = None  # (p, t, ts)
        self._baseline_reason: str = "новая сессия наблюдения"
        # The authoritative moment the operator entered the phase, distinct from
        # the timestamp of the first sample that could actually be measured
        # after it. Conflating them overstates what the baseline is anchored to.
        self._phase_entry_epoch: float | None = None
        # Readings older than this are refused when establishing a baseline, so
        # a cached pre-transition sample cannot become the new zero.
        self._baseline_fence_ts: float | None = None
        self._phase_identity: tuple[str, str, float] | None = None
        # Written by the pipeline via plain attribute assignment; consumed in
        # process(). Declaring it is how this plugin opts in — the pipeline
        # never calls a method to deliver it, so no plugin code runs outside
        # process() on any path.
        self.pending_phase_event = None
        self._history: list[tuple[float, float]] = []  # (ts, n_rel_pct)
        self._last_emit_ts: float = 0.0
        self._binding_error: str | None = None
        self._awaiting_selection: bool = False

    # ------------------------------------------------------------------
    # configuration
    # ------------------------------------------------------------------
    def configure(self, config: dict[str, Any]) -> None:
        super().configure(config)

        self._pressure_channel = str(config.get("pressure_channel", "")).strip()
        raw_sensors = config.get("bulk_sensors") or []
        if isinstance(raw_sensors, str):
            raw_sensors = [raw_sensors]
        self._bulk_sensors = [str(s).strip() for s in raw_sensors if str(s).strip()]

        # 0 means "every batch". The default is slow on purpose — the quantity
        # moves over hours — but there is no reason to forbid an unthrottled
        # configuration, and clamping to a 1 s floor silently discarded samples.
        try:
            self._update_interval_s = max(0.0, float(config.get("update_interval_s", 60.0)))
        except (TypeError, ValueError):
            self._update_interval_s = 60.0

        # Rebinding starts a new measurement. A baseline captured against one set
        # of sensors means nothing against another, and carrying it across would
        # silently rescale every subsequent reading.
        # A restart or a plugin reload loses the phase baseline: nothing is
        # persisted and no durable reconstruction exists. Say so, rather than
        # letting a new zero inherit the previous phase's wording and look
        # authoritative. `_phase` is cleared too, so the next genuine phase
        # notification is treated as an entry rather than a duplicate.
        self._phase_identity = None
        self.pending_phase_event = None
        self.reset_baseline(reason="новая сессия наблюдения")
        self._last.clear()
        self._runtime_label.clear()

        self._binding_error = self._validate_bindings()
        if self._binding_error is not None:
            if self._awaiting_selection:
                _log.info(
                    "MolecularCounter: %s. Счёт недоступен, пока датчики не выбраны.",
                    self._binding_error,
                )
            else:
                _log.error(
                    "MolecularCounter: %s. Счёт НЕДОСТУПЕН до исправления конфигурации.",
                    self._binding_error,
                )
            return

        _log.info(
            "MolecularCounter: давление=%s, объём газа по %d датчикам (%s), интервал %.0f с",
            self._pressure_channel,
            len(self._bulk_sensors),
            ", ".join(self._bulk_sensors),
            self._update_interval_s,
        )

    def _validate_bindings(self) -> str | None:
        """Refuse to compute rather than compute from assumptions."""

        self._awaiting_selection = False
        if not self._pressure_channel:
            return "не задан канал давления (pressure_channel)"
        if not self._bulk_sensors:
            self._awaiting_selection = True
            return "не выбраны датчики объёма газа (bulk_sensors)"
        if len(set(self._bulk_sensors)) != len(self._bulk_sensors):
            return "в bulk_sensors есть повторяющиеся каналы"
        if self._pressure_channel in self._bulk_sensors:
            return "канал давления указан и как датчик объёма газа"
        return None

    # ------------------------------------------------------------------
    # baseline
    # ------------------------------------------------------------------
    def reset_baseline(
        self,
        *,
        reason: str = "сброс оператором",
        fence_ts: float | None = None,
        phase_entry_epoch: float | None = None,
    ) -> None:
        """Drop the baseline; the next valid sample becomes the new 100%.

        The operator owns what "100%" means — normally the start of a cooldown.
        The plugin never re-baselines on its own, because a baseline that moves
        without being asked makes every past reading incomparable.
        """

        if self._baseline is not None:
            _log.info("MolecularCounter: базовая линия сброшена (%s)", reason)
        self._baseline = None
        self._baseline_reason = reason
        self._baseline_fence_ts = fence_ts
        self._phase_entry_epoch = phase_entry_epoch
        self._history.clear()

    @property
    def baseline_epoch(self) -> float | None:
        return None if self._baseline is None else self._baseline[2]

    @property
    def baseline_reason(self) -> str:
        """Operator-facing description of what 100% currently means."""

        return self._baseline_reason

    def _consume_phase_event(self) -> None:
        """Apply the latest authoritative phase entry, if it is a new one.

        Runs inside `process()`, so this is the plugin's own already-accounted-
        for execution — the pipeline never calls into plugin code to deliver it,
        it only assigns `pending_phase_event`.

        What "100%" means is a property of the phase. During `vacuum` the useful
        zero is the start of pumping; during `cooldown` it is the start of
        cooling, which is what made 2026-09-03 legible at 100 -> 80 -> 118%.
        Zeroed at pump-down that run reads 3% -> 3.5% and the crossing vanishes.

        Identity is the whole (experiment, phase, started_at) triple, so
        re-entering a phase is a NEW entry rather than a duplicate, and the
        baseline is anchored to the manager's own `started_at` rather than to
        whenever this happened to run.
        """

        entry = self.pending_phase_event
        if entry is None:
            return
        try:
            identity = entry.identity()
            phase = str(entry.phase)
            started_at = float(entry.started_at)
        except (AttributeError, TypeError, ValueError):
            return
        if identity == self._phase_identity:
            return
        label = _PHASE_BASELINE_LABELS.get(phase)
        if label is None:
            # An unrecognised phase is not a reason to discard a measurement.
            return
        if not math.isfinite(started_at):
            return
        self._phase_identity = identity
        self.reset_baseline(reason=label, fence_ts=started_at, phase_entry_epoch=started_at)

    async def process(self, readings: list[Reading]) -> list[DerivedMetric]:
        if self._binding_error is not None:
            return []

        # One reference moment for the whole batch. Measuring each input against
        # the cache as it is written would let an old value look fresh simply
        # because a newer one arrived beside it.
        now = datetime.now(UTC).timestamp()
        self._consume_phase_event()
        self._absorb(readings, now)

        if now - self._last_emit_ts < self._update_interval_s:
            return []

        pressure = self._current(self._pressure_channel, now)
        if pressure is None or pressure <= 0.0:
            return []

        # EVERY configured sensor, or nothing. Averaging whichever subset
        # happens to be present changes the denominator underneath a fixed
        # baseline: with two sensors configured and only the first reporting,
        # the counter reads 100%, then 50% when the second appears at unchanged
        # pressure. A moving denominator cannot sit under one zero.
        temps: list[float] = []
        for sensor in self._bulk_sensors:
            value = self._current(sensor, now)
            if value is None or value < _MIN_PHYSICAL_K:
                return []
            temps.append(value)
        if not temps:
            return []
        t_bulk = sum(temps) / len(temps)

        if self._baseline is None:
            if not self._inputs_pass_fence(now):
                # Still waiting for readings acquired AFTER the phase entry.
                return []
            self._baseline = (pressure, t_bulk, now)
            _log.info(
                "MolecularCounter: базовая линия — P=%.5g мбар, T=%.1f K, %d датчиков (%s; вход в фазу %s)",
                pressure,
                t_bulk,
                len(temps),
                self._baseline_reason,
                "—" if self._phase_entry_epoch is None else f"{now - self._phase_entry_epoch:.0f} с назад",
            )

        p0, t0, baseline_ts = self._baseline
        # N ∝ P/T, single zone. NOT a bound in either direction: the mean of
        # selected sensors is not the volume-weighted effective gas temperature.
        n_rel_pct = 100.0 * (pressure / p0) * (t0 / t_bulk)
        if not math.isfinite(n_rel_pct):
            return []

        self._last_emit_ts = now
        self._history.append((now, n_rel_pct))
        cutoff = now - _RATE_WINDOW_S
        self._history = [(ts, v) for ts, v in self._history if ts >= cutoff]

        rate = self._rate_pct_per_h()

        return [
            DerivedMetric.now(
                self.plugin_id,
                "gas_inventory",
                round(n_rel_pct, 2),
                "%",
                metadata={
                    "n_relative_pct": round(n_rel_pct, 2),
                    # Fractional: percent of the CURRENT inventory per hour, so the
                    # number stays meaningful across a five-decade pump-down.
                    "rate_pct_per_h": None if rate is None else round(rate, 3),
                    "rate_is_fractional": True,
                    "pressure_mbar": pressure,
                    "t_bulk_k": round(t_bulk, 2),
                    "sensors_used": len(temps),
                    "sensors_configured": len(self._bulk_sensors),
                    "baseline_epoch": baseline_ts,
                    "baseline_pressure_mbar": p0,
                    "baseline_t_bulk_k": round(t0, 2),
                    "baseline_age_s": round(now - baseline_ts, 1),
                    # The operator action, distinct from the first sample that
                    # could be measured after it.
                    "phase_entry_epoch": self._phase_entry_epoch,
                    # 100% is never implied. Every value carries what its zero
                    # was and when it was taken, so the number is unambiguous
                    # even hours later in a log or a report.
                    "baseline_reason": self._baseline_reason,
                    # The one-zone assumption, stated with every value it produces.
                    "model": "single_zone_apparent",
                    # No lower-bound or direction guarantee is claimed: the mean
                    # of selected sensors is not the volume-weighted effective
                    # gas temperature, and a Pirani reading is composition
                    # dependent.
                    "quantity": "apparent_temperature_corrected_pirani_equivalent",
                    "rate_definition": "100*d(ln N)/dt",
                },
            )
        ]

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _absorb(self, readings: list[Reading], now: float) -> None:
        wanted = [self._pressure_channel, *self._bulk_sensors]
        for reading in readings:
            if reading.status is not ChannelStatus.OK:
                continue
            value = reading.value
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                continue
            runtime = str(reading.channel)
            for configured in wanted:
                if matches_channel_id(runtime, configured):
                    try:
                        ts = float(reading.timestamp.timestamp())
                    except (TypeError, ValueError, OSError, AttributeError):
                        # Fail closed. Substituting `now` for an unreadable
                        # timestamp makes an undateable reading look fresh, and
                        # freshness is the entire basis for using it.
                        break
                    if not math.isfinite(ts):
                        break
                    self._last[configured] = (float(value), ts)
                    self._runtime_label[configured] = runtime
                    break

    def _inputs_pass_fence(self, now: float) -> bool:
        """True when every input in use was acquired after the fence."""

        fence = self._baseline_fence_ts
        if fence is None:
            return True
        for configured in (self._pressure_channel, *self._bulk_sensors):
            entry = self._last.get(configured)
            if entry is not None and entry[1] < fence:
                return False
        return True

    def _current(self, configured: str, now: float) -> float | None:
        """Value only if it still describes now. Fails closed."""

        entry = self._last.get(configured)
        if entry is None:
            return None
        value, ts = entry
        if not judge_freshness(ts, now_epoch=now, max_age_s=_INPUT_WINDOW_S).is_current:
            return None
        return value

    def _rate_pct_per_h(self) -> float | None:
        """Apparent logarithmic inventory rate: 100·d(ln N)/dt, in %/h.

        NOT a bounded fractional loss. -69.3 %/h is a halving per hour, not
        "69.3% of the contents gone"; the unit is a continuous log slope and its
        magnitude can exceed 100.

        Relative to what is in the chamber NOW, not to the baseline. A slope of
        `n_rel_pct` answers "percent of the ORIGINAL load per hour", which is
        meaningless once the original load is gone: zero the counter at 1 bar
        and by 1e-2 mbar the inventory is 0.001% of baseline, so a full decade of
        further pumping moves that slope by a rounding error and the readout goes
        flat exactly where the work is happening.

        A log slope is scale-invariant — "losing 5% of what is in there per hour"
        means the same at 1 bar and at 1e-5 mbar — so one number serves a
        five-decade pump-down and a sub-decade cooldown alike.
        """

        # A CONTIGUOUS TRAILING RUN only. Filtering invalid points out of the
        # middle and fitting across the hole silently bridges a gap: a
        # zero/NaN/inf sample, or one with an unusable timestamp, means the
        # series was interrupted, and a slope drawn across that interruption is
        # an invention. Walk backwards and stop at the first bad point.
        points: list[tuple[float, float]] = []
        for ts, value in reversed(self._history):
            if not isinstance(ts, (int, float)) or not math.isfinite(ts):
                break
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0.0:
                break
            if points and ts >= points[-1][0]:
                # Non-monotonic time: the run is not contiguous either.
                break
            if points and (points[-1][0] - ts) > _MAX_SAMPLE_GAP_S:
                # Silence longer than one sampling interval. Nothing was written
                # to mark it, so the gap itself is the only evidence that the
                # series was interrupted.
                break
            points.append((float(ts), float(value)))
        points.reverse()

        if len(points) < 3:
            return None
        span = points[-1][0] - points[0][0]
        if span < _MIN_RATE_SPAN_S:
            # Not enough elapsed time to speak about a rate. Reporting None is
            # the honest answer; the value itself is still published. The span
            # is measured on the RETAINED run, not on the whole buffer.
            return None
        t0 = points[0][0]
        xs = [(ts - t0) / 3600.0 for ts, _ in points]
        ys = [math.log(v) for _, v in points]
        n = len(xs)
        mx = sum(xs) / n
        my = sum(ys) / n
        denom = sum((x - mx) ** 2 for x in xs)
        if denom <= 0.0:
            return None
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False)) / denom
        if not math.isfinite(slope):
            return None
        return 100.0 * slope


__all__ = ["MolecularCounter"]
