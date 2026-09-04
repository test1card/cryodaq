"""VacuumGuard — pressure × reference-temperature alarm for cold cryostat.

Fully automatic: no operator arm/disarm. State driven by physical conditions.
Arms when T_ref drops below arm_threshold; fires when vacuum degrades sustained.
10K hysteresis on T_ref, one decade on pressure.

State machine: DISARMED → ARMED → FIRED (and back).
All transitions read fresh state per tick from ChannelStateTracker (LATE BINDING).
"""

from __future__ import annotations

import enum
import logging
import math
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cryodaq.core.alarm_v2 import AlarmStateManager
    from cryodaq.core.channel_state import ChannelStateTracker
    from cryodaq.core.event_bus import EventBus

logger = logging.getLogger(__name__)

ALARM_ID = "vacuum_guard"


class VacuumState(enum.Enum):
    DISARMED = "DISARMED"
    ARMED = "ARMED"
    FIRED = "FIRED"


class VacuumGuard:
    """Pressure × T_ref guard alarm for cryogenic operations.

    Arms automatically when T_ref < arm_threshold_K (system is cold).
    Fires when pressure exceeds fire_pressure_mbar for sustained_s seconds.
    All thresholds have deadband to prevent chatter.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        state_tracker: ChannelStateTracker,
        alarm_state_mgr: AlarmStateManager,
        event_bus: EventBus,
    ) -> None:
        self._state_tracker = state_tracker
        self._alarm_state_mgr = alarm_state_mgr
        self._event_bus = event_bus
        # This guard annunciates and nothing else. It holds no handle on the
        # source and cannot be given one: the parameter is gone, so restoring
        # that authority is a TypeError rather than a one-word wiring change.
        # Source state belongs to SafetyManager — hard limits, interlocks,
        # source faults, persistence and safety shutdowns, operator E-stop.

        self._pressure_ch: str = cfg.get("pressure_channel", "VSP63D_1/pressure")
        self._ref_temp_ch: str = cfg.get("reference_temp_channel", "Т12")
        self._arm_threshold_K: float = float(cfg.get("arm_threshold_K", 260.0))
        self._disarm_threshold_K: float = float(cfg.get("disarm_threshold_K", 270.0))
        self._fire_pressure: float = float(cfg.get("fire_pressure_mbar", 1.0e-2))
        self._clear_pressure: float = float(cfg.get("clear_pressure_mbar", 1.0e-3))
        self._sustained_s: float = float(cfg.get("sustained_s", 30))

        # --- Fractional rise detection -------------------------------------
        # A level threshold cannot separate "this stand's vacuum" from "the
        # vacuum is failing". On 2026-09-03 the guard fired 31 s after its
        # temperature gate opened, at 7.3e-2 mbar against a 1.0e-2 threshold —
        # 73x over — and every cooldown this stand has recorded crossed 260 K
        # between 7.3e-2 and 9.8e-1 mbar. It was reporting the gate, not an event.
        #
        # A vacuum loss is a RISE. And the rise must be fractional, not absolute:
        # +0.001 mbar/h is catastrophic at 1e-5 mbar and invisible at 5e-2, so an
        # mbar/h threshold is wrong by orders of magnitude at one end or the other.
        # 100*d(ln P)/dt means the same thing at every pressure.
        #
        # Disabled unless configured, so the level path stands alone until an
        # operator opts in.
        rise = cfg.get("fire_rise_pct_per_h")
        self._fire_rise: float | None = float(rise) if rise is not None else None
        clear_rise = cfg.get("clear_rise_pct_per_h")
        self._clear_rise: float = float(clear_rise) if clear_rise is not None else 10.0
        self._rise_window_s: float = float(cfg.get("rise_window_s", 600.0))
        # A slope needs a baseline in TIME. Fitted over seconds, one gauge
        # quantization step reads as tens of percent per hour — measuring this
        # stand's own history produced a spurious +71.5 %/h from a single 0.00016
        # mbar step across a database rollover. Half the window is the floor.
        self._min_rise_span_s: float = self._rise_window_s * 0.5
        self._pressure_history: list[tuple[float, float]] = []
        self._rise_sustained_since: float | None = None
        self._severity: str = str(cfg.get("severity", "CRITICAL"))

        self._state = VacuumState.DISARMED
        self._sustained_since: float | None = None

        logger.info(
            "VacuumGuard: P-канал=%s, T-опорная=%s, порог арм.=%.0f K",
            self._pressure_ch,
            self._ref_temp_ch,
            self._arm_threshold_K,
        )

    @property
    def state(self) -> VacuumState:
        return self._state

    def _fractional_rise_pct_per_h(self) -> float | None:
        """100·d(ln P)/dt over the rise window, or None if it cannot be said.

        Fractional so one threshold holds across every decade the gauge covers.
        Returns None rather than a number whenever the window is too short in
        TIME — a slope fitted over seconds turns gauge quantization into tens of
        percent per hour.
        """

        points = [(t, v) for t, v in self._pressure_history if v > 0.0]
        if len(points) < 3:
            return None
        span = points[-1][0] - points[0][0]
        if span < self._min_rise_span_s:
            return None
        t0 = points[0][0]
        xs = [(t - t0) / 3600.0 for t, _ in points]
        ys = [math.log(v) for _, v in points]
        n = len(xs)
        mx = sum(xs) / n
        my = sum(ys) / n
        denom = sum((x - mx) ** 2 for x in xs)
        if denom <= 0.0:
            return None
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False)) / denom
        return 100.0 * slope if math.isfinite(slope) else None

    async def tick(self) -> None:
        """Evaluate vacuum guard state. Called every eval_interval_s by engine."""
        # Read T_ref fresh per tick (LATE BINDING via ChannelStateTracker)
        t_ref_state = self._state_tracker.get(self._ref_temp_ch)
        if t_ref_state is None or t_ref_state.is_stale:
            logger.debug("VacuumGuard: T-опорная %s недоступна — пропуск", self._ref_temp_ch)
            # Do not clear an active FIRED alarm — sensor dropout during hazard keeps alarm.
            if self._state != VacuumState.FIRED:
                self._alarm_state_mgr.process(ALARM_ID, None, {})
            return None

        t_ref = t_ref_state.value

        # Read pressure fresh per tick
        p_state = self._state_tracker.get(self._pressure_ch)
        if p_state is None or p_state.is_stale:
            logger.debug("VacuumGuard: P-канал %s недоступен — пропуск", self._pressure_ch)
            # Do not clear FIRED alarm on sensor dropout — keep alarm until data returns.
            if self._state != VacuumState.FIRED:
                self._alarm_state_mgr.process(ALARM_ID, None, {})
            return None

        p_mbar = p_state.value
        prev_state = self._state

        # --- State transitions (sequential — ARMED evaluation runs on the same tick as arming) ---

        # Step 1: warm condition always wins
        if t_ref >= self._disarm_threshold_K:
            self._state = VacuumState.DISARMED
            self._sustained_since = None

        # Step 2: arm when cold (may transition from DISARMED → ARMED this tick)
        if self._state == VacuumState.DISARMED and t_ref < self._arm_threshold_K:
            self._state = VacuumState.ARMED
            logger.info(
                "VacuumGuard: ARMED (T-опорная=%.1f K < %.0f K)",
                t_ref,
                self._arm_threshold_K,
            )

        # Record pressure history for the fractional-rise path.
        now_mono = time.monotonic()
        if p_mbar > 0.0:
            self._pressure_history.append((now_mono, p_mbar))
            cutoff = now_mono - self._rise_window_s
            self._pressure_history = [(t, v) for t, v in self._pressure_history if t >= cutoff]
        rise_pct_per_h = self._fractional_rise_pct_per_h()

        # Step 3: pressure recovery when FIRED (deadband)
        if self._state == VacuumState.FIRED and p_mbar < self._clear_pressure:
            self._state = VacuumState.ARMED
            self._sustained_since = None
            logger.info("VacuumGuard: ARMED (вакуум восстановлен, P=%.2e мбар)", p_mbar)

        # Step 4: pressure evaluation when ARMED — runs on the same tick as arming
        # so a sustained bad vacuum fires without waiting an extra interval.
        if self._state == VacuumState.ARMED:
            if p_mbar > self._fire_pressure:
                if self._sustained_since is None:
                    self._sustained_since = time.monotonic()
                if time.monotonic() - self._sustained_since >= self._sustained_s:
                    self._state = VacuumState.FIRED
                    logger.warning(
                        "VacuumGuard: FIRED (P=%.2e мбар, T-опорная=%.1f K)",
                        p_mbar,
                        t_ref,
                    )
            else:
                self._sustained_since = None

            # Fractional-rise path, independent of the level backstop above.
            if self._state == VacuumState.ARMED and self._fire_rise is not None:
                if rise_pct_per_h is not None and rise_pct_per_h > self._fire_rise:
                    if self._rise_sustained_since is None:
                        self._rise_sustained_since = now_mono
                    if now_mono - self._rise_sustained_since >= self._sustained_s:
                        self._state = VacuumState.FIRED
                        logger.warning(
                            "VacuumGuard: FIRED (рост давления %+.0f %%/ч > %+.0f %%/ч, P=%.2e мбар, T-опорная=%.1f K)",
                            rise_pct_per_h,
                            self._fire_rise,
                            p_mbar,
                            t_ref,
                        )
                else:
                    self._rise_sustained_since = None

        # Recovery from a rise-triggered fire: the rise has to stop, not the level.
        if (
            self._state == VacuumState.FIRED
            and self._fire_rise is not None
            and rise_pct_per_h is not None
            and rise_pct_per_h < self._clear_rise
            and p_mbar <= self._fire_pressure
        ):
            self._state = VacuumState.ARMED
            self._rise_sustained_since = None
            self._sustained_since = None
            logger.info("VacuumGuard: ARMED (рост прекратился, %+.0f %%/ч)", rise_pct_per_h)

        if prev_state != self._state:
            await self._publish_state_event()

        # --- Fire through AlarmStateManager ---
        from cryodaq.core.alarm_v2 import AlarmEvent

        if self._state == VacuumState.FIRED:
            event: AlarmEvent | None = AlarmEvent(
                alarm_id=ALARM_ID,
                level=self._severity,
                message=(
                    f"P = {p_mbar:.2e} мбар (порог {self._fire_pressure:.1e} мбар). "
                    f"{self._ref_temp_ch} = {t_ref:.0f} K (ниже {self._arm_threshold_K:.0f} K). "
                    f"Требуется вмешательство оператора."
                ),
                triggered_at=time.time(),
                channels=[self._pressure_ch, self._ref_temp_ch],
                values={self._pressure_ch: p_mbar, self._ref_temp_ch: t_ref},
            )
        else:
            event = None

        transition = self._alarm_state_mgr.process(ALARM_ID, event, {"sustained_s": None, "hysteresis": None})

        # A FIRED edge used to latch a SafetyManager fault here, cutting the
        # source. It fired on the first cooldown it ever saw, on a threshold
        # every recorded cooldown on this stand would have crossed, and held the
        # manager latched for eleven hours — during which the cryocooler CRITICAL
        # arrived and left as a single INFO line. Losing vacuum while cold is
        # worth waking someone for; it is not the software's call to make.
        return transition

    async def _publish_state_event(self) -> None:
        from cryodaq.core.event_bus import EngineEvent

        try:
            await self._event_bus.publish(
                EngineEvent(
                    event_type="vacuum_guard.state_changed",
                    timestamp=datetime.now(UTC),
                    payload={"state": self._state.value},
                )
            )
        except Exception as exc:
            logger.debug("VacuumGuard: ошибка публикации события: %s", exc)
