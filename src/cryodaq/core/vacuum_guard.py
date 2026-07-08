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
        safety_manager: Any = None,
    ) -> None:
        self._state_tracker = state_tracker
        self._alarm_state_mgr = alarm_state_mgr
        self._event_bus = event_bus
        # Opt-in SafetyManager escalation (external safety review, HIGH).
        # The engine passes a handle ONLY when config sets
        # escalate_to_safety: true (strict bool, fail-closed) — so a
        # non-None handle IS the operator opt-in. When set, a FIRED-edge
        # additionally latches a SafetyManager fault (source OFF +
        # FAULT_LATCHED) so a vacuum incident while cold stops the source,
        # not just raises an alarm. None = today's alarm-only behavior.
        self._safety_manager = safety_manager

        self._pressure_ch: str = cfg.get("pressure_channel", "VSP63D_1/pressure")
        self._ref_temp_ch: str = cfg.get("reference_temp_channel", "Т12")
        self._arm_threshold_K: float = float(cfg.get("arm_threshold_K", 260.0))
        self._disarm_threshold_K: float = float(cfg.get("disarm_threshold_K", 270.0))
        self._fire_pressure: float = float(cfg.get("fire_pressure_mbar", 1.0e-2))
        self._clear_pressure: float = float(cfg.get("clear_pressure_mbar", 1.0e-3))
        self._sustained_s: float = float(cfg.get("sustained_s", 30))
        self._severity: str = str(cfg.get("severity", "CRITICAL"))

        self._state = VacuumState.DISARMED
        self._sustained_since: float | None = None

        logger.info(
            "VacuumGuard: P-канал=%s, T-опорная=%s, порог арм.=%.0f K",
            self._pressure_ch, self._ref_temp_ch, self._arm_threshold_K,
        )

    @property
    def state(self) -> VacuumState:
        return self._state

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
                t_ref, self._arm_threshold_K,
            )

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
                        p_mbar, t_ref,
                    )
            else:
                self._sustained_since = None

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

        transition = self._alarm_state_mgr.process(
            ALARM_ID, event, {"sustained_s": None, "hysteresis": None}
        )

        # Opt-in escalation: latch a SafetyManager fault on the FIRED edge only.
        # Gated on the transition INTO FIRED so the fault latches once per
        # incident, not on every tick while FIRED. A recovery (FIRED→ARMED) and
        # re-trip (ARMED→FIRED) is a fresh edge → escalates again. No auto-clear
        # when pressure recovers: latch_fault drives the normal FAULT_LATCHED →
        # acknowledge → MANUAL_RECOVERY flow — a cold-vacuum incident needs
        # operator eyes. The handle is present only when the operator enabled
        # escalate_to_safety.
        just_fired = prev_state != VacuumState.FIRED and self._state == VacuumState.FIRED
        if just_fired and self._safety_manager is not None:
            reason = (
                f"Потеря вакуума при холодном криостате: P = {p_mbar:.2e} мбар "
                f"(порог {self._fire_pressure:.1e} мбар), {self._ref_temp_ch} = "
                f"{t_ref:.0f} K (ниже порога арм. {self._arm_threshold_K:.0f} K). "
                f"Эскалация в SafetyManager включена оператором "
                f"(escalate_to_safety)."
            )
            try:
                await self._safety_manager.latch_fault(
                    reason=reason,
                    source="vacuum_guard",
                    channel=self._pressure_ch,
                    value=p_mbar,
                )
            except Exception as exc:
                # Latch failure is logged, never re-raised — the tick task must
                # keep running so the CRITICAL still surfaces via the alarm path.
                logger.error(
                    "VacuumGuard: latch_fault failed (non-fatal): %s",
                    exc,
                    exc_info=True,
                )

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
