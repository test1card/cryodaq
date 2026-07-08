"""CooldownAlarm — predictor-based trajectory deviation alarm + measurement watchdog.

Operator-armed. Uses CooldownPredictor ensemble model to detect when
a cooldown is falling significantly behind its expected trajectory.

State machine:
  DISARMED → ARMED → WATCHING → FIRED ↔ WATCHING
                              → AUTO_DISARMED → WATCHDOG → WATCHDOG_FIRED ↔ WATCHDOG

WATCHDOG: monitors T_cold only after cooldown completes; fires WARNING on warming.
WATCHDOG → DISARMED via operator disarm() or experiment.finalized notification.
All data reads are fresh per tick from ChannelStateTracker (LATE BINDING).
Graceful degradation: model absent → arm() returns False, alarm stays DISARMED.
"""
from __future__ import annotations

import collections
import enum
import logging
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cryodaq.core.alarm_v2 import AlarmStateManager
    from cryodaq.core.channel_state import ChannelStateTracker
    from cryodaq.core.event_bus import EventBus

logger = logging.getLogger(__name__)

ALARM_ID = "cooldown_alarm"
WATCHDOG_ALARM_ID = "cooldown_watchdog"
_RATE_MIN_HISTORY_H = 0.5  # minimum elapsed hours before deviation logic activates


class CooldownState(enum.Enum):
    DISARMED = "DISARMED"
    ARMED = "ARMED"               # collecting baseline (< RATE_MIN_HISTORY_H elapsed)
    WATCHING = "WATCHING"         # evaluating trajectory
    FIRED = "FIRED"               # trajectory alarm active
    AUTO_DISARMED = "AUTO_DISARMED"   # cooldown complete; momentary if watchdog_enabled
    WATCHDOG = "WATCHDOG"         # monitoring T_cold post-cooldown
    WATCHDOG_FIRED = "WATCHDOG_FIRED" # warming detected


class CooldownAlarm:
    """Predictor-based trajectory deviation alarm with post-cooldown watchdog.

    Operator presses "Запустить контроль захолаживания" → arm().
    Predictor model loaded lazily on first arm (not at construction).
    Deviation computed as (expected_progress - actual_progress) / σ_progress.
    After AUTO_DISARMED (cooldown complete), transitions to WATCHDOG if enabled.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        state_tracker: ChannelStateTracker,
        alarm_state_mgr: AlarmStateManager,
        event_bus: EventBus,
        steady_state_predictor: Any = None,
        safety_manager: Any = None,
    ) -> None:
        self._state_tracker = state_tracker
        self._alarm_state_mgr = alarm_state_mgr
        self._event_bus = event_bus
        # v0.55.4 A2: optional SteadyStatePredictor reference. When the
        # predictor reports is_quasi_steady=True for the cold channel,
        # the deviation check is skipped — system already settled,
        # gas-desorption drift would otherwise look like trajectory
        # divergence to the curve-fit predictor.
        self._steady_state_predictor = steady_state_predictor
        # v0.55.12 — public SafetyManager handle for CRITICAL escalation
        # via latch_fault() (audit SCOPE 1 finding 1.1). Optional
        # so unit tests that don't care about the safety wiring can
        # construct the alarm without a SafetyManager mock.
        self._safety_manager = safety_manager

        self._cold_ch: str = cfg.get("cold_channel", "Т12")
        self._warm_ch: str = cfg.get("warm_channel", "Т11")
        self._k_p: float = float(cfg.get("k_p", 2.5))
        self._sustained_min: int = int(cfg.get("sustained_min", 5))
        self._base_temp_K: float = float(cfg.get("base_temp_K", 5.0))
        self._base_epsilon_K: float = float(cfg.get("base_epsilon_K", 1.0))
        self._auto_disarm_progress: float = float(cfg.get("auto_disarm_progress", 0.95))
        self._eta_slip_window_min: float = float(cfg.get("eta_slip_window_min", 60))
        self._eta_slip_threshold_h: float = float(cfg.get("eta_slip_message_threshold_h", 0.5))

        # v0.55.4 A1: opt-in auto-arm on cooldown phase entry. Engine
        # consults `is_auto_arm_enabled` after a phase transition and
        # calls arm() when true; operator can still disarm manually.
        self._auto_arm: bool = bool(cfg.get("auto_arm", True))

        # Watchdog config — v0.55.4 A3: default flipped to False per
        # architect rule. If post-cooldown drift bumps the system back
        # out of quasi-steady, CooldownAlarm WATCHING catches it via
        # the predictor — no separate watchdog logic needed for the
        # contest demo. Single config flip restores it.
        self._watchdog_enabled: bool = bool(cfg.get("watchdog_enabled", False))
        self._watchdog_margin_K: float = float(cfg.get("watchdog_margin_K", 1.0))
        self._watchdog_level: str = str(cfg.get("watchdog_level", "WARNING"))
        _watchdog_sustained_s: float = float(cfg.get("watchdog_sustained_s", 300.0))
        _eval_interval_s: float = float(cfg.get("eval_interval_s", 30.0))
        self._watchdog_required_ticks: int = max(1, math.ceil(_watchdog_sustained_s / _eval_interval_s))

        model_path_str = cfg.get("predictor_model_path", "data/cooldown_model/predictor_model.json")
        self._model_dir = Path(model_path_str).parent

        # v0.55.12 — cold-start auto-detect (audit SCOPE 1 finding 1.5).
        # On engine restart with the cryostat already cold, auto_arm fires,
        # arm() succeeds, and the very first tick triggers AUTO_DISARMED
        # before the quasi-steady gate runs — leaving the alarm in a
        # terminal state with watchdog default off. Skip arm() when the
        # cold channel is already in [base, base + cold_start_skip_margin_K]
        # AND (if available) SteadyStatePredictor reports quasi-steady.
        self._cold_start_skip_margin_K: float = float(
            cfg.get("cold_start_skip_margin_K", 5.0)
        )
        self._cold_start_skipped: bool = False

        self._state = CooldownState.DISARMED
        self._model = None               # EnsembleModel — loaded on arm()
        self._t_armed: float | None = None
        self._sustained_count: int = 0
        self._watchdog_sustained_count: int = 0
        self._current_progress: float | None = None
        self._current_eta_h: float | None = None
        self._finalize_requested: bool = False
        # v0.55.12 — monotonic cycle generation, incremented on every
        # disarm() / phase-away transition. Captured at tick() start;
        # any in-flight tick that returns to a yield point with a stale
        # generation aborts before publishing CRITICAL or escalating to
        # SafetyManager (audit SCOPE 1 finding 1.3).
        self._cycle_generation: int = 0

        # Circular buffer of (wall_time, eta_h) for slip computation
        self._eta_history: collections.deque = collections.deque(
            maxlen=int(self._eta_slip_window_min * 2 + 10)
        )

    @property
    def state(self) -> CooldownState:
        return self._state

    @property
    def is_auto_arm_enabled(self) -> bool:
        """v0.55.4 A1: engine consults this after a phase transition
        into cooldown. When True it calls arm() automatically;
        operator retains manual disarm via «Контроль захолаживания».
        """
        return self._auto_arm

    def set_steady_state_predictor(self, predictor: Any) -> None:
        """Engine wiring for v0.55.4 A2: CooldownService creates the
        SteadyStatePredictor after CooldownAlarm; this setter lets the
        engine inject it once both exist without reordering bootstrap.
        """
        self._steady_state_predictor = predictor

    @property
    def current_eta_h(self) -> float | None:
        return self._current_eta_h

    @property
    def current_progress(self) -> float | None:
        return self._current_progress

    @property
    def cold_start_skipped(self) -> bool:
        """v0.55.12 — last arm() refused due to cold-start detection.

        Engine reads this after auto-arm to log a clear "cold-start
        detected, skipping" line; cleared on the next explicit
        ``notify_phase_change("cooldown")`` call so a subsequent
        operator-initiated cooldown re-evaluates the gate.
        """
        return self._cold_start_skipped

    def _is_cold_start(self) -> bool:
        """v0.55.12 — true if the cryostat is already at base T.

        Detection rule (architect 2026-05-07): cold channel reading is
        in ``[base_temp_K, base_temp_K + cold_start_skip_margin_K]`` AND
        (if available) SteadyStatePredictor reports
        ``is_quasi_steady=True`` for the cold channel. Stale readings
        and a missing channel state both yield False — without fresh
        evidence we err on the side of arming.
        """
        cold_state = self._state_tracker.get(self._cold_ch)
        if cold_state is None or cold_state.is_stale:
            return False

        base_max = self._base_temp_K + self._cold_start_skip_margin_K
        if not (self._base_temp_K <= cold_state.value <= base_max):
            return False

        # SteadyStatePredictor optional. When present, require
        # quasi-steady on the cold channel before declaring cold-start —
        # gas-desorption drift / late-evening recovery shouldn't count.
        if self._steady_state_predictor is not None:
            try:
                ss_pred = self._steady_state_predictor.get_prediction(
                    self._cold_ch
                )
            except Exception:
                return False
            if ss_pred is None or not getattr(ss_pred, "is_quasi_steady", False):
                return False

        return True

    def arm(self) -> bool:
        """Load predictor model and start monitoring. Returns False if model absent."""
        # v0.55.12 — cold-start gate (audit SCOPE 1 finding 1.5).
        # Skip arm() entirely when the cryostat is already at base T;
        # otherwise the very first tick runs auto_disarm and lands the
        # alarm in terminal AUTO_DISARMED with watchdog default off.
        if self._is_cold_start():
            cold_state = self._state_tracker.get(self._cold_ch)
            warm_state = self._state_tracker.get(self._warm_ch)
            cold_str = (
                f"{cold_state.value:.2f}" if cold_state is not None else "?"
            )
            warm_str = (
                f"{warm_state.value:.2f}" if warm_state is not None else "?"
            )
            logger.info(
                "CooldownAlarm: cold-start detected (T_cold=%s K, T_warm=%s K, "
                "base=[%.1f, %.1f]) — skipping auto-arm",
                cold_str,
                warm_str,
                self._base_temp_K,
                self._base_temp_K + self._cold_start_skip_margin_K,
            )
            self._cold_start_skipped = True
            return False
        # Made it past the gate; clear flag so a stale True from a
        # previous restart doesn't linger after the system warmed up.
        self._cold_start_skipped = False

        if self._state in (
            CooldownState.AUTO_DISARMED,
            CooldownState.WATCHDOG,
            CooldownState.WATCHDOG_FIRED,
        ):
            # Clear any active watchdog alarm before re-arming
            self._alarm_state_mgr.process(WATCHDOG_ALARM_ID, None, {})
            self._watchdog_sustained_count = 0
            self._state = CooldownState.DISARMED
            logger.info("CooldownAlarm: сброс для нового цикла захолаживания")

        # Lazy model load
        if self._model is None:
            model_file = self._model_dir / "predictor_model.json"
            if not model_file.exists():
                logger.warning(
                    "CooldownAlarm: модель %s не найдена — запустите cryodaq-cooldown build",
                    model_file,
                )
                return False
            try:
                from cryodaq.analytics.cooldown_predictor import load_model
                self._model = load_model(self._model_dir)
                logger.info(
                    "CooldownAlarm: модель загружена (%d кривых, %.1f ч среднее)",
                    self._model.n_curves, self._model.duration_mean,
                )
            except Exception as exc:
                logger.warning("CooldownAlarm: ошибка загрузки модели: %s", exc)
                return False

        self._t_armed = time.monotonic()
        self._sustained_count = 0
        self._current_progress = None
        self._current_eta_h = None
        self._eta_history.clear()
        self._finalize_requested = False
        self._state = CooldownState.ARMED
        logger.info("CooldownAlarm: ARMED")
        return True

    def disarm(self) -> None:
        """Operator-requested stop. Clears all active alarms (both IDs)."""
        # v0.55.12 — bump cycle generation FIRST so any in-flight tick
        # that returns to a yield-point sees the stale cycle and aborts
        # before publishing CRITICAL or escalating to SafetyManager
        # (audit SCOPE 1 finding 1.3).
        self._cycle_generation += 1
        self._state = CooldownState.DISARMED
        self._sustained_count = 0
        self._watchdog_sustained_count = 0
        self._finalize_requested = False
        self._current_eta_h = None
        self._current_progress = None
        self._alarm_state_mgr.process(ALARM_ID, None, {})
        self._alarm_state_mgr.process(WATCHDOG_ALARM_ID, None, {})
        logger.info("CooldownAlarm: DISARMED (оператор)")

    def notify_experiment_finalized(self) -> None:
        """Called by engine when experiment is finalized. Transitions WATCHDOG → DISARMED."""
        self._finalize_requested = True

    def notify_phase_change(self, new_phase: str) -> None:
        """v0.55.12 — engine wires this to ``experiment_advance_phase``.

        Two responsibilities (audit SCOPE 1 findings 1.2 + 1.5):

        - When the operator advances *into* the cooldown phase, clear
          ``cold_start_skipped`` so the auto-arm gate re-evaluates
          fresh (e.g. cryostat warmed up since the last skip).
        - When the operator advances to any phase *other than*
          cooldown while the alarm is active (ARMED / WATCHING / FIRED
          / AUTO_DISARMED / WATCHDOG / WATCHDOG_FIRED), disarm and
          clear active alarms — the previous behaviour left the alarm
          stuck because only ``finalize`` cleared state.

        Idempotent: a no-op if the alarm is already DISARMED and the
        new phase is not cooldown.
        """
        if new_phase == "cooldown":
            self._cold_start_skipped = False
            return
        if self._state == CooldownState.DISARMED:
            return
        logger.info(
            "CooldownAlarm: phase=%s ≠ cooldown — disarming (was %s)",
            new_phase,
            self._state.value,
        )
        # disarm() bumps the cycle generation, so any in-flight tick
        # that resumes will detect the stale cycle and abort.
        self.disarm()

    async def tick(self) -> None:
        """Evaluate trajectory. Called every eval_interval_s by engine."""
        # v0.55.12 — capture cycle generation; re-checked before any
        # destructive emit (alarm-state publish, latch_fault) to detect
        # mid-tick disarm/phase-change. audit SCOPE 1 finding 1.3.
        cycle = self._cycle_generation

        # Handle finalize notification — single flag, safe in asyncio single-thread
        if self._finalize_requested:
            self._finalize_requested = False
            if self._state != CooldownState.DISARMED:
                self.disarm()
            return

        if self._state in (CooldownState.DISARMED, CooldownState.AUTO_DISARMED):
            return

        # WATCHDOG has its own tick path (predictor not running)
        if self._state in (CooldownState.WATCHDOG, CooldownState.WATCHDOG_FIRED):
            return await self._watchdog_tick()

        # --- ARMED / WATCHING / FIRED path (predictor active) ---

        # Read temperatures fresh per tick (LATE BINDING)
        cold_state = self._state_tracker.get(self._cold_ch)
        warm_state = self._state_tracker.get(self._warm_ch)

        if cold_state is None or cold_state.is_stale:
            logger.debug("CooldownAlarm: %s недоступен — пропуск", self._cold_ch)
            return
        if warm_state is None or warm_state.is_stale:
            logger.debug("CooldownAlarm: %s недоступен — пропуск", self._warm_ch)
            return

        T_cold = cold_state.value
        T_warm = warm_state.value
        t_elapsed_s = time.monotonic() - self._t_armed  # type: ignore[operator]
        t_elapsed_h = t_elapsed_s / 3600.0

        # --- Auto-disarm check ---
        auto_disarm_base = self._base_temp_K + self._base_epsilon_K
        if T_cold <= auto_disarm_base or (
            self._current_progress is not None
            and self._current_progress >= self._auto_disarm_progress
        ):
            self._state = CooldownState.AUTO_DISARMED
            transition = self._alarm_state_mgr.process(ALARM_ID, None, {})
            await self._publish_state_event()
            logger.info(
                "CooldownAlarm: AUTO_DISARMED (T_холод=%.2f K, прогресс=%s)",
                T_cold,
                f"{self._current_progress:.0%}" if self._current_progress is not None else "н/д",
            )
            # Immediately enter WATCHDOG if enabled — AUTO_DISARMED is momentary
            if self._watchdog_enabled:
                self._watchdog_sustained_count = 0
                self._state = CooldownState.WATCHDOG
                await self._publish_state_event()
                logger.info("CooldownAlarm: WATCHDOG (контроль измерения начат)")
            return transition

        # --- Baseline collection phase ---
        if t_elapsed_h < _RATE_MIN_HISTORY_H:
            self._state = CooldownState.ARMED
            return

        if self._state == CooldownState.ARMED:
            self._state = CooldownState.WATCHING
            await self._publish_state_event()

        # v0.55.4 A2 — quasi-steady gate. When SteadyStatePredictor
        # reports the cold channel is sitting near steady, the curve-fit
        # cooldown predictor would interpret gas-desorption drift as
        # trajectory divergence. Skip the deviation check; if currently
        # FIRED, drop back to WATCHING and clear the alarm. If the system
        # later warms back up, SteadyStatePredictor will exit
        # is_quasi_steady=True naturally and this branch stops short-
        # circuiting — WATCHING resumes the deviation evaluation.
        if self._steady_state_predictor is not None:
            try:
                ss_pred = self._steady_state_predictor.get_prediction(self._cold_ch)
            except Exception:
                ss_pred = None
            if ss_pred is not None and getattr(ss_pred, "is_quasi_steady", False):
                if self._state == CooldownState.FIRED:
                    self._state = CooldownState.WATCHING
                    self._sustained_count = 0
                    self._alarm_state_mgr.process(ALARM_ID, None, {})
                    await self._publish_state_event()
                    logger.info(
                        "CooldownAlarm: quasi-steady — FIRED → WATCHING (T_cold=%.2f K)",
                        T_cold,
                    )
                else:
                    self._sustained_count = 0
                return

        # --- Predictor evaluation ---
        try:
            from cryodaq.analytics.cooldown_predictor import predict as _predict
            pred = _predict(self._model, T_cold, T_warm, t_elapsed=t_elapsed_h)
        except Exception as exc:
            logger.warning("CooldownAlarm: ошибка предиктора: %s", exc)
            return

        p_actual = pred.progress
        eta_h = pred.t_remaining_hours
        self._current_progress = p_actual
        self._current_eta_h = eta_h

        # Track ETA history for slip computation
        now_wall = time.time()
        self._eta_history.append((now_wall, eta_h))

        # --- Expected progress at this elapsed time ---
        p_expected: float
        try:
            if self._model._p_of_t_mean is not None:
                p_expected = float(self._model._p_of_t_mean(t_elapsed_h))
                p_expected = max(0.0, min(1.0, p_expected))
            else:
                p_expected = min(1.0, t_elapsed_h / max(self._model.duration_mean, 0.1))
        except Exception:
            p_expected = min(1.0, t_elapsed_h / max(self._model.duration_mean, 0.1))

        # --- Uncertainty estimate (fractional) ---
        sigma_p = (self._model.duration_std / max(self._model.duration_mean, 0.1)) * 0.5

        deviation = p_expected - p_actual

        # --- ETA slip ---
        eta_slip_h: float | None = None
        slip_window_s = self._eta_slip_window_min * 60.0
        old_entries = [(t, e) for t, e in self._eta_history if now_wall - t >= slip_window_s * 0.9]
        if old_entries:
            eta_1h_ago = old_entries[-1][1]
            eta_slip_h = eta_h - (eta_1h_ago - self._eta_slip_window_min / 60.0)

        # --- Fire condition ---
        in_deviation = (
            deviation > self._k_p * sigma_p
            and T_cold > auto_disarm_base
        )

        if in_deviation:
            self._sustained_count += 1
        else:
            self._sustained_count = 0

        from cryodaq.core.alarm_v2 import AlarmEvent

        just_fired = False
        if self._sustained_count >= self._sustained_min:
            slip_msg = ""
            if eta_slip_h is not None and eta_slip_h > self._eta_slip_threshold_h:
                slip_msg = (
                    f" ETA сдвинулась на +{eta_slip_h:.1f} ч за последний час."
                )
            event: AlarmEvent | None = AlarmEvent(
                alarm_id=ALARM_ID,
                level="CRITICAL",
                message=(
                    f"Захолаживание не идёт по плану. "
                    f"Прогресс {p_actual:.0%} вместо ожидаемых {p_expected:.0%} "
                    f"(отклонение {deviation / max(sigma_p, 0.01):.1f}σ). "
                    f"{self._cold_ch} = {T_cold:.1f} K."
                    + slip_msg
                ),
                triggered_at=time.time(),
                channels=[self._cold_ch, self._warm_ch],
                values={self._cold_ch: T_cold, self._warm_ch: T_warm},
            )
            if self._state != CooldownState.FIRED:
                just_fired = True
                self._state = CooldownState.FIRED
                await self._publish_state_event()
        else:
            event = None
            if self._state == CooldownState.FIRED:
                self._state = CooldownState.WATCHING
                await self._publish_state_event()

        # v0.55.12 — cycle re-check before destructive emit (audit
        # SCOPE 1 finding 1.3). If disarm() or notify_phase_change() ran
        # while we were awaiting the publish above, the captured cycle is
        # now stale and we must NOT publish a CRITICAL on a now-DISARMED
        # alarm.
        if cycle != self._cycle_generation:
            logger.info(
                "CooldownAlarm: tick aborted — cycle invalidated (was %d, now %d)",
                cycle,
                self._cycle_generation,
            )
            return None

        transition = self._alarm_state_mgr.process(
            ALARM_ID, event, {"sustained_s": None, "hysteresis": None}
        )

        # v0.55.12 — escalate CRITICAL to SafetyManager via the public
        # latch_fault() entry point (audit SCOPE 1 finding 1.1).
        # Gated on the FIRED-edge so we fire the safety latch once per
        # cycle, not on every WATCHING tick after the alarm clears or
        # repeats.
        if (
            just_fired
            and event is not None
            and event.level == "CRITICAL"
            and cycle == self._cycle_generation
            and self._safety_manager is not None
        ):
            try:
                await self._safety_manager.latch_fault(
                    reason=event.message,
                    source="cooldown_alarm",
                )
            except Exception as exc:
                # Latch failure is logged but never re-raised — the
                # tick task must keep running so the alarm-state manager
                # path still surfaces the CRITICAL via Telegram /
                # operator log.
                logger.error(
                    "CooldownAlarm: latch_fault failed (non-fatal): %s",
                    exc,
                    exc_info=True,
                )

        return transition

    async def _watchdog_tick(self) -> None:
        """Tick logic for WATCHDOG / WATCHDOG_FIRED states (predictor not running)."""
        cold_state = self._state_tracker.get(self._cold_ch)
        if cold_state is None or cold_state.is_stale:
            logger.debug("CooldownAlarm WATCHDOG: %s недоступен — пропуск", self._cold_ch)
            return

        T_cold = cold_state.value
        threshold = self._base_temp_K + self._watchdog_margin_K

        from cryodaq.core.alarm_v2 import AlarmEvent

        if T_cold > threshold:
            self._watchdog_sustained_count += 1
        else:
            self._watchdog_sustained_count = 0
            if self._state == CooldownState.WATCHDOG_FIRED:
                self._state = CooldownState.WATCHDOG
                await self._publish_state_event()

        if self._watchdog_sustained_count >= self._watchdog_required_ticks:
            event: AlarmEvent | None = AlarmEvent(
                alarm_id=WATCHDOG_ALARM_ID,
                level=self._watchdog_level,
                message=(
                    f"Холодная ступень ({self._cold_ch}) "
                    f"греется при измерении: {T_cold:.2f} K "
                    f"(порог {threshold:.2f} K)"
                ),
                triggered_at=time.time(),
                channels=[self._cold_ch],
                values={self._cold_ch: T_cold},
            )
            if self._state != CooldownState.WATCHDOG_FIRED:
                self._state = CooldownState.WATCHDOG_FIRED
                await self._publish_state_event()
        else:
            event = None

        return self._alarm_state_mgr.process(
            WATCHDOG_ALARM_ID, event, {"sustained_s": None, "hysteresis": None}
        )

    async def _publish_state_event(self) -> None:
        from cryodaq.core.event_bus import EngineEvent
        try:
            await self._event_bus.publish(
                EngineEvent(
                    event_type="cooldown_alarm.state_changed",
                    timestamp=datetime.now(UTC),
                    payload={
                        "state": self._state.value,
                        "progress": self._current_progress,
                        "eta_h": self._current_eta_h,
                    },
                )
            )
        except Exception as exc:
            logger.debug("CooldownAlarm: ошибка публикации события: %s", exc)
