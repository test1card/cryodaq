"""Счётчик молекул: сколько газа реально осталось в камере.

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

Единственная модель — однозонная: весь газ считается при средней температуре
выбранных датчиков. Это НАМЕРЕННО консервативная оценка. Реальная камера имеет
холодные зоны, которые дают ещё меньшее P при том же N, поэтому истинное
значение N/N₀ всегда НЕ МЕНЬШЕ показанного. Проверено на данных 03.09: при
однозонном расчёте 96.3% на h=7, при правдоподобных долях холодного объёма —
111–124%. Показываем нижнюю границу, а не выдуманную точность.

Замечания к интерпретации, которые счётчик не может исправить сам:

* Pirani VSP63D откалиброван по N₂. Сдвиг состава к лёгким газам (H₂, He)
  смещает МАСШТАБ; НАПРАВЛЕНИЕ остаётся верным, а направление и есть то, по
  чему принимают решение.
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
        self._baseline_reason: str = "начало наблюдения"
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
        self.reset_baseline(reason="configure")
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
    def reset_baseline(self, *, reason: str = "сброс оператором") -> None:
        """Drop the baseline; the next valid sample becomes the new 100%.

        The operator owns what "100%" means — normally the start of a cooldown.
        The plugin never re-baselines on its own, because a baseline that moves
        without being asked makes every past reading incomparable.
        """

        if self._baseline is not None:
            _log.info("MolecularCounter: базовая линия сброшена (%s)", reason)
        self._baseline = None
        self._baseline_reason = reason
        self._history.clear()

    @property
    def baseline_epoch(self) -> float | None:
        return None if self._baseline is None else self._baseline[2]

    @property
    def baseline_reason(self) -> str:
        """Operator-facing description of what 100% currently means."""

        return self._baseline_reason

    def notify_phase_change(self, phase: str | None) -> None:
        """Re-zero when the operator advances the phase.

        What "100%" means is a property of the phase, and one fixed zero cannot
        serve both questions. During `vacuum` the useful zero is the start of
        pumping — "how much of the load have I removed?", which is the number
        for drying the MLI. During `cooldown` it is the start of cooling — "is
        the chamber holding what it had?", which is what made 2026-09-03
        legible: 100% → 80% → 118%, crossing back above its own start. Zeroed at
        pump-down instead, that same run would have read 3% → 3.5% and the
        crossing would have been invisible.

        This does not violate the rule that the counter never re-zeros itself. A
        phase change is an operator action; the zero moves because someone moved
        it, indirectly but deliberately. It is never moved by the data.
        """

        label = _PHASE_BASELINE_LABELS.get(str(phase or ""), None)
        if label is None:
            # An unknown phase is not a reason to discard a good baseline.
            return
        self.reset_baseline(reason=label)

    # ------------------------------------------------------------------
    # processing
    # ------------------------------------------------------------------
    async def process(self, readings: list[Reading]) -> list[DerivedMetric]:
        if self._binding_error is not None:
            return []

        # One reference moment for the whole batch. Measuring each input against
        # the cache as it is written would let an old value look fresh simply
        # because a newer one arrived beside it.
        now = datetime.now(UTC).timestamp()
        self._absorb(readings, now)

        if now - self._last_emit_ts < self._update_interval_s:
            return []

        pressure = self._current(self._pressure_channel, now)
        if pressure is None or pressure <= 0.0:
            return []

        temps = [t for t in (self._current(s, now) for s in self._bulk_sensors) if t is not None]
        temps = [t for t in temps if t >= _MIN_PHYSICAL_K]
        if not temps:
            return []
        t_bulk = sum(temps) / len(temps)

        if self._baseline is None:
            self._baseline = (pressure, t_bulk, now)
            _log.info(
                "MolecularCounter: базовая линия — P=%.5g мбар, T=%.1f K, %d датчиков",
                pressure,
                t_bulk,
                len(temps),
            )

        p0, t0, baseline_ts = self._baseline
        # N ∝ P/T, single zone. Conservative: real cold zones make the true
        # inventory higher than this, never lower.
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
                    # 100% is never implied. Every value carries what its zero
                    # was and when it was taken, so the number is unambiguous
                    # even hours later in a log or a report.
                    "baseline_reason": self._baseline_reason,
                    # The one-zone assumption, stated with every value it produces.
                    "model": "single_zone",
                    "is_lower_bound": True,
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
                        ts = now
                    self._last[configured] = (float(value), ts)
                    self._runtime_label[configured] = runtime
                    break

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
        """Fractional change per hour: 100·d(ln N)/dt.

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

        if len(self._history) < 3:
            return None
        span = self._history[-1][0] - self._history[0][0]
        if span < _MIN_RATE_SPAN_S:
            # Not enough elapsed time to speak about a rate. Reporting None is
            # the honest answer; the value itself is still published.
            return None
        points = [(ts, v) for ts, v in self._history if v > 0.0]
        if len(points) < 3:
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
