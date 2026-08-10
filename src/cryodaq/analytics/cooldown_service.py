"""Сервис прогнозирования охлаждения для CryoDAQ Engine.

Интегрирует cooldown_predictor с DataBroker:
- CooldownDetector: определяет начало/конец цикла охлаждения
- CooldownService: asyncio-сервис, подписывается на брокер,
  периодически вызывает predict(), публикует DerivedMetric
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from cryodaq.core.event_bus import EventBus

from cryodaq.analytics.base_plugin import DerivedMetric
from cryodaq.analytics.cooldown_predictor import (
    MIN_COOLDOWN_MODEL_CURVES,
    CooldownModelStatus,
    EnsembleModel,
    PredictionResult,
    compute_rate_from_history,
    cooldown_curve_source_digest,
    ingest_from_raw_arrays,
    load_model,
    predict,
)
from cryodaq.analytics.steady_state import SteadyStatePredictor
from cryodaq.core.broker import DataBroker
from cryodaq.core.shutdown_settlement import (
    CancelledTaskSettlement,
    await_executor_owner,
    cancel_and_settle_tasks,
    combine_settlements,
    settle_executor_operation,
    settle_without_cancelling,
)
from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)


# ============================================================================
# Cooldown detector: state machine for cycle detection
# ============================================================================


class CooldownPhase(Enum):
    """Фаза цикла охлаждения."""

    IDLE = "idle"
    COOLING = "cooling"
    STABILIZING = "stabilizing"
    COMPLETE = "complete"


class CooldownDetector:
    """Определяет начало/конец цикла охлаждения по потоку данных.

    Переходы состояний:
        IDLE -> COOLING: dT_cold/dt < start_rate_threshold в течение confirm_minutes
        COOLING -> STABILIZING: T_cold < end_T_threshold
        STABILIZING -> COMPLETE: |dT/dt| < end_rate_threshold в течение confirm_minutes
        COMPLETE -> IDLE: после вызова reset() (auto-ingest завершён)
    """

    def __init__(
        self,
        start_rate_threshold: float = -5.0,
        start_confirm_minutes: float = 10.0,
        end_T_cold_threshold: float = 6.0,
        end_rate_threshold: float = 0.1,
        end_confirm_minutes: float = 30.0,
    ) -> None:
        self._start_rate_thr = start_rate_threshold
        self._start_confirm_s = start_confirm_minutes * 60.0
        self._end_T_thr = end_T_cold_threshold
        self._end_rate_thr = end_rate_threshold
        self._end_confirm_s = end_confirm_minutes * 60.0

        self._phase = CooldownPhase.IDLE
        self._confirm_start_ts: float | None = None
        self._confirm_end_ts: float | None = None
        self._cooldown_start_ts: float | None = None

        # Sliding window for dT/dt estimation (last 5 min)
        self._recent: deque[tuple[float, float]] = deque(maxlen=60)

    @property
    def phase(self) -> CooldownPhase:
        return self._phase

    @property
    def cooldown_start_ts(self) -> float | None:
        return self._cooldown_start_ts

    def reset(self) -> None:
        """Сброс в IDLE (после auto-ingest)."""
        self._phase = CooldownPhase.IDLE
        self._confirm_start_ts = None
        self._confirm_end_ts = None
        self._cooldown_start_ts = None
        self._recent.clear()

    def update(self, ts: float, T_cold: float) -> CooldownPhase:
        """Обновить состояние детектора по новому показанию.

        Args:
            ts: монотонное время (time.monotonic()) в секундах
            T_cold: текущая температура холодной ступени, K

        Returns:
            Текущая фаза после обновления.
        """
        self._recent.append((ts, T_cold))

        # Estimate dT/dt from recent window
        dT_dt = self._estimate_rate()

        if self._phase == CooldownPhase.IDLE:
            if dT_dt is not None and dT_dt < self._start_rate_thr:
                if self._confirm_start_ts is None:
                    self._confirm_start_ts = ts
                elif ts - self._confirm_start_ts >= self._start_confirm_s:
                    self._phase = CooldownPhase.COOLING
                    self._cooldown_start_ts = self._confirm_start_ts
                    self._confirm_start_ts = None
                    logger.info(
                        "Обнаружено начало охлаждения: dT/dt=%.1f K/ч, T_cold=%.1f K",
                        dT_dt,
                        T_cold,
                    )
            else:
                self._confirm_start_ts = None

        elif self._phase == CooldownPhase.COOLING:
            if T_cold < self._end_T_thr:
                self._phase = CooldownPhase.STABILIZING
                logger.info(
                    "Охлаждение -> стабилизация: T_cold=%.2f K < %.1f K",
                    T_cold,
                    self._end_T_thr,
                )

        elif self._phase == CooldownPhase.STABILIZING:
            if dT_dt is not None and abs(dT_dt) < self._end_rate_thr:
                if self._confirm_end_ts is None:
                    self._confirm_end_ts = ts
                elif ts - self._confirm_end_ts >= self._end_confirm_s:
                    self._phase = CooldownPhase.COMPLETE
                    self._confirm_end_ts = None
                    logger.info(
                        "Охлаждение завершено: T_cold=%.2f K, |dT/dt|=%.3f K/ч",
                        T_cold,
                        abs(dT_dt) if dT_dt else 0.0,
                    )
            else:
                self._confirm_end_ts = None

        return self._phase

    def _estimate_rate(self) -> float | None:
        """Оценить dT/dt [K/ч] по скользящему окну."""
        if len(self._recent) < 5:
            return None
        ts_arr = [p[0] for p in self._recent]
        T_arr = [p[1] for p in self._recent]
        dt_s = ts_arr[-1] - ts_arr[0]
        if dt_s < 30.0:
            return None
        dT = T_arr[-1] - T_arr[0]
        # Convert to K/h
        return dT / (dt_s / 3600.0)


# ============================================================================
# CooldownService: asyncio integration with DataBroker
# ============================================================================


class CooldownService:
    """Асинхронный сервис прогнозирования охлаждения.

    Подписывается на DataBroker, собирает данные каналов cold/warm
    в кольцевой буфер, периодически вызывает predict() и публикует
    DerivedMetric через ZMQ.
    """

    def __init__(
        self,
        broker: DataBroker,
        config: dict[str, Any],
        model_dir: Path,
        *,
        event_bus: EventBus | None = None,
        reader: Any | None = None,
        safety_manager: Any = None,
    ) -> None:
        self._broker = broker
        self._config = config
        self._model_dir = model_dir
        # A1: engine EventBus for the cooldown-end push event (optional so
        # unit tests and headless paths can omit it).
        self._event_bus = event_bus
        # A2: read-only history reader (SQLiteWriter.read_readings_history)
        # for off-hot-path ultimate_vacuum enrichment at cooldown end.
        self._reader = reader
        # P0 fail-open fix — optional SafetyManager handle (same pattern as
        # CooldownAlarm's ``safety_manager``), so unit tests and headless
        # paths can construct CooldownService without safety wiring. When
        # set, _start_locked() reports predictor model health through
        # SafetyManager.set_cooldown_predictor_status() so a missing,
        # malformed, or below-minimum model blocks request_run() via the
        # existing precondition gate instead of silently reporting
        # available. NOT wired from engine.py yet in this candidate — see
        # implementer report; that one-line construction-site change is
        # outside this fix's writable surface.
        self._safety_manager = safety_manager

        self._channel_cold: str = config.get("channel_cold", "")
        self._channel_warm: str = config.get("channel_warm", "")
        self._predict_interval_s: float = float(config.get("predict_interval_s", 30))
        self._rate_window_h: float = float(config.get("rate_window_h", 1.5))
        self._auto_ingest: bool = bool(config.get("auto_ingest", True))
        self._min_cooldown_hours: float = float(config.get("min_cooldown_hours", 10.0))

        # Detector config
        det_cfg = config.get("detect", {})
        self._detector = CooldownDetector(
            start_rate_threshold=float(det_cfg.get("start_rate_threshold", -5.0)),
            start_confirm_minutes=float(det_cfg.get("start_confirm_minutes", 10)),
            end_T_cold_threshold=float(det_cfg.get("end_T_cold_threshold", 6.0)),
            end_rate_threshold=float(det_cfg.get("end_rate_threshold", 0.1)),
            end_confirm_minutes=float(det_cfg.get("end_confirm_minutes", 30)),
        )

        # Ring buffer: (t_hours_from_start, T_cold, T_warm)
        self._buffer: deque[tuple[float, float, float]] = deque(maxlen=100_000)
        self._cooldown_wall_start: float | None = None

        # Model
        self._model: EnsembleModel | None = None
        # P0 fail-open fix — typed status of the last attempt to establish
        # self._model, never a bare None/bool (see CooldownModelStatus).
        # None until _start_locked has run at least once.
        self.model_status: CooldownModelStatus | None = None

        # Queue & tasks
        self._queue: asyncio.Queue | None = None
        self._consume_task: asyncio.Task | None = None
        self._predict_task: asyncio.Task | None = None
        self._running = False
        self._stopping = False
        self._lifecycle_lock = asyncio.Lock()
        self._executor_admission_open = True
        self._executor_futures: set[asyncio.Task[Any]] = set()

        # Latest T values for detector
        self._last_T_cold: float | None = None
        self._last_T_warm: float | None = None
        self._last_required_input_monotonic: dict[str, float] = {}

        # Task 8a: lazily-loaded cooldown_baseline config from plugins.yaml
        # (None = not loaded yet). The fingerprint tap is flag-guarded and
        # off the hot path, so we read plugins.yaml once, on first cooldown end.
        self._baseline_cfg: dict[str, Any] | None = None

        # F-ReplayPredictor (v0.56.3): track latest reading timestamp from
        # the data stream so predict() works correctly with accelerated
        # replay (where wall-clock time and reading timestamps decouple).
        self._last_reading_ts: float | None = None

        # Cached prediction for query agent (F30)
        self._last_prediction: dict[str, Any] | None = None
        # v0.55.3 — raw PredictionResult kept alongside the dict summary
        # so expected_value() can interpolate the future_t / future_T_*
        # arrays for PhysicsAlarmDetector (v0.55.4).
        self._last_prediction_raw: PredictionResult | None = None
        # v0.55.3 — quasi-steady regime predictor. Engine feeds it via
        # cooldown.yaml `steady_state:` block; defaults preserved when
        # the block is absent so existing deployments do not regress.
        ss_cfg = config.get("steady_state", {}) or {}
        self._ss_predictor = SteadyStatePredictor(
            window_s=float(ss_cfg.get("window_s", 900.0)),
            update_interval_s=float(ss_cfg.get("update_interval_s", 10.0)),
            min_points=int(ss_cfg.get("min_points", 30)),
            min_duration_s=float(ss_cfg.get("min_duration_s", 60.0)),
            noise_floor_k=float(ss_cfg.get("noise_floor_k", 0.05)),
            drift_threshold_k_per_h=float(ss_cfg.get("drift_threshold_k_per_h", 1.0)),
        )

    @property
    def phase(self) -> CooldownPhase:
        return self._detector.phase

    def last_prediction(self) -> dict[str, Any] | None:
        """Return last computed prediction metadata, or None if not yet predicted."""
        return self._last_prediction

    def expected_value(self, channel: str, ts_monotonic: float) -> tuple[float, float] | None:
        """Interpolate expected (T, sigma) at ``ts_monotonic`` for the given channel.

        Returns ``None`` if any precondition is unmet:
        - no model loaded yet,
        - cooldown phase outside ``{COOLING, STABILIZING}``,
        - no cached prediction yet,
        - channel not in ``{channel_cold, channel_warm}``,
        - no future trajectory in the cached prediction (pre-COOLING run),
        - ``ts_monotonic`` falls outside the future_t horizon.

        Implementation note: ``PredictionResult.future_t`` is in HOURS
        since cooldown_start, ``ts_monotonic`` is wall-clock seconds, so
        we project ts back through ``self._cooldown_wall_start``.
        ``future_T_cold_upper / lower`` are mean ± 1σ (see
        cooldown_predictor.py:625-629), so half the band width is the
        sigma at that point.

        Designed for v0.55.4 PhysicsAlarmDetector — exposes the trajectory
        without forcing every consumer to round-trip through the metadata
        dict.
        """
        if self._model is None:
            return None
        if self._detector.phase not in (CooldownPhase.COOLING, CooldownPhase.STABILIZING):
            return None
        pred = self._last_prediction_raw
        if pred is None or pred.future_t is None:
            return None
        if self._cooldown_wall_start is None:
            return None
        if channel == self._channel_cold:
            mean_arr = pred.future_T_cold_mean
            upper_arr = pred.future_T_cold_upper
            lower_arr = pred.future_T_cold_lower
        elif channel == self._channel_warm:
            mean_arr = getattr(pred, "future_T_warm_mean", None)
            upper_arr = getattr(pred, "future_T_warm_upper", None)
            lower_arr = getattr(pred, "future_T_warm_lower", None)
        else:
            return None
        if mean_arr is None or upper_arr is None or lower_arr is None:
            return None

        # TODO (v0.56.3 follow-up): same wall-vs-reading clock pattern as
        # _do_predict — if the caller (PhysicsAlarmDetector) passes
        # time.time() while _cooldown_wall_start was seeded from
        # reading.timestamp, ``target_h`` will undercount under
        # accelerated replay. Verify caller before swapping ts_monotonic
        # for self._last_reading_ts; demo blocker is _do_predict only.
        target_h = (ts_monotonic - self._cooldown_wall_start) / 3600.0
        future_t = pred.future_t
        if target_h < float(future_t[0]) or target_h > float(future_t[-1]):
            return None
        mean_val = float(np.interp(target_h, future_t, mean_arr))
        upper_val = float(np.interp(target_h, future_t, upper_arr))
        lower_val = float(np.interp(target_h, future_t, lower_arr))
        sigma = max(0.0, (upper_val - lower_val) / 2.0)
        return (mean_val, sigma)

    def _lifecycle_transition_lock(self) -> asyncio.Lock:
        """Return the single owner that serializes start/stop generations."""

        lock = getattr(self, "_lifecycle_lock", None)
        if lock is None:
            # Compatibility for partially constructed terminal-settlement
            # owners. Creation is atomic on one event loop.
            lock = asyncio.Lock()
            self._lifecycle_lock = lock
        return lock

    async def start(self) -> None:
        """Start exactly one lifecycle generation."""

        async with self._lifecycle_transition_lock():
            try:
                await self._start_locked()
            except asyncio.CancelledError as cancellation:
                await self._settle_cancelled_start(cancellation)
                raise cancellation
            except BaseException:
                await self._settle_partial_start()
                raise

    async def _settle_cancelled_start(self, cancellation: asyncio.CancelledError) -> None:
        """Rollback every partial startup owner before propagating cancellation."""

        await self._settle_partial_start(cancellation)

    async def _settle_partial_start(
        self,
        cancellation: asyncio.CancelledError | None = None,
    ) -> None:
        """Settle only owners acquired by this partial startup generation."""

        self._stopping = True
        self._executor_admission_open = False
        self._running = False
        combined: CancelledTaskSettlement | None = None
        try:
            tasks = tuple(task for task in (self._consume_task, self._predict_task) if task is not None)
            executor_futures = tuple(getattr(self, "_executor_futures", ()))
            task_settlement = await cancel_and_settle_tasks(tasks)
            executor_settlement = await settle_without_cancelling(
                executor_futures,
                name="cooldown-start-executor-settlement",
            )
            queue = self._queue
            if queue is None:
                unsubscribe_settlement = CancelledTaskSettlement()
            else:
                unsubscribe = asyncio.create_task(
                    self._broker.unsubscribe(
                        "cooldown_service",
                        expected_queue=queue,
                    ),
                    name="cooldown-start-subscription-settlement",
                )
                unsubscribe_settlement = await settle_without_cancelling(
                    (unsubscribe,),
                    name="cooldown-start-subscription-drain",
                )
            self._consume_task = None
            self._predict_task = None
            self._queue = None
            if hasattr(self, "_executor_futures"):
                self._executor_futures.clear()
            combined = combine_settlements(
                task_settlement,
                executor_settlement,
                unsubscribe_settlement,
                CancelledTaskSettlement(cancellation=cancellation),
            )
        finally:
            self._stopping = False
        assert combined is not None
        combined.raise_if_unsuccessful()

    async def _start_locked(self) -> None:
        """Запустить сервис: подписка на брокер, загрузка модели, запуск задач."""
        consume_live = self._consume_task is not None and not self._consume_task.done()
        predict_live = self._predict_task is not None and not self._predict_task.done()
        if self._running and consume_live and predict_live and self._queue is not None:
            return
        if self._stopping:
            raise RuntimeError("cooldown service cannot start while shutdown is settling")
        if (
            self._running
            or self._queue is not None
            or self._consume_task is not None
            or self._predict_task is not None
            or self._executor_futures
        ):
            await self._stop_locked()
        self._executor_admission_open = True

        channels = {self._channel_cold, self._channel_warm}

        def _filter(reading: Reading) -> bool:
            return reading.channel in channels

        self._queue = await self._broker.subscribe(
            "cooldown_service",
            maxsize=5000,
            filter_fn=_filter,
        )

        # Load model (in executor, may be slow).
        #
        # P0 fail-open fix: a missing, malformed, or below-minimum-curve
        # model must never present as usable safety infrastructure. Every
        # branch below sets self.model_status to a typed CooldownModelStatus
        # (never a bare None/bool) and, when a SafetyManager is wired in
        # (see __init__), reports it through set_cooldown_predictor_status()
        # — the existing request_run() precondition gate
        # (SafetyManager._check_preconditions()) then denies RUN and the
        # SAFE_OFF -> READY auto-transition until a later available=True
        # report clears it. This never touches OFF/emergency-off authority:
        # SafetyManager remains the sole authority for source on/off, and
        # this is a new *fact* fed into its existing gate, not a second one.
        try:
            model_file = self._model_dir / "predictor_model.json"
            if model_file.exists():
                loaded_model = await self._run_owned_executor(load_model, self._model_dir)
                if not self._executor_admission_open:
                    return
                if loaded_model.n_curves < MIN_COOLDOWN_MODEL_CURVES:
                    # Defense in depth (item 2, third enforcement point):
                    # load_model()/_require_model_capacity() already reject a
                    # below-minimum on-disk model before this line can be
                    # reached, but this call site — the one that actually
                    # adopts a model as self._model — is re-checked
                    # explicitly so it can never adopt one by any other path
                    # or future refactor of load_model().
                    raise ValueError(
                        f"loaded cooldown model has {loaded_model.n_curves} curve(s), "
                        f"below the reviewed minimum {MIN_COOLDOWN_MODEL_CURVES}"
                    )
                self._model = loaded_model
                self.model_status = CooldownModelStatus(available=True)
                logger.info(
                    "Модель охлаждения загружена: %d кривых, %.1f +/- %.1f ч",
                    self._model.n_curves,
                    self._model.duration_mean,
                    self._model.duration_std,
                )
            else:
                reason = f"predictor model file not found: {model_file}"
                logger.warning(
                    "Файл модели не найден: %s — прогнозирование недоступно",
                    model_file,
                )
                self.model_status = CooldownModelStatus(available=False, reason=reason)
        except Exception as exc:
            if isinstance(exc.__cause__, asyncio.CancelledError):
                raise
            reason = f"{type(exc).__name__}: {exc}"
            logger.error("Ошибка загрузки модели охлаждения: %s", exc)
            self.model_status = CooldownModelStatus(available=False, reason=reason)

        if self._safety_manager is not None and self.model_status is not None:
            await self._safety_manager.set_cooldown_predictor_status(
                self.model_status.available,
                self.model_status.reason,
            )

        if not self._executor_admission_open:
            return
        self._running = True
        self._consume_task = asyncio.create_task(
            self._consume_loop(),
            name="cooldown_consume",
        )
        self._predict_task = asyncio.create_task(
            self._predict_loop(),
            name="cooldown_predict",
        )
        logger.info("CooldownService запущен")

    async def stop(self) -> None:
        """Settle one lifecycle generation without racing a replacement."""

        async with self._lifecycle_transition_lock():
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        """Остановить сервис: отмена задач, отписка от брокера."""
        self._stopping = True
        self._executor_admission_open = False
        self._running = False
        combined: CancelledTaskSettlement | None = None
        try:
            tasks = tuple(task for task in (self._consume_task, self._predict_task) if task is not None)
            executor_futures = tuple(getattr(self, "_executor_futures", ()))
            task_settlement = await cancel_and_settle_tasks(tasks)
            executor_settlement = await settle_without_cancelling(
                executor_futures,
                name="cooldown-executor-terminal-settlement",
            )
            queue = self._queue
            if queue is None:
                unsubscribe_settlement = CancelledTaskSettlement()
            else:
                unsubscribe = asyncio.create_task(
                    self._broker.unsubscribe(
                        "cooldown_service",
                        expected_queue=queue,
                    ),
                    name="cooldown-unsubscribe-terminal-settlement",
                )
                unsubscribe_settlement = await settle_without_cancelling(
                    (unsubscribe,),
                    name="cooldown-unsubscribe-drain",
                )
            self._consume_task = None
            self._predict_task = None
            self._executor_futures.clear()
            self._queue = None
            combined = combine_settlements(
                task_settlement,
                executor_settlement,
                unsubscribe_settlement,
            )
        finally:
            self._stopping = False
        assert combined is not None
        combined.raise_if_unsuccessful()
        logger.info("CooldownService остановлен")

    async def _run_owned_executor[ExecutorResult](
        self,
        function: Callable[..., ExecutorResult],
        /,
        *args: Any,
    ) -> ExecutorResult:
        if not self._executor_admission_open:
            raise RuntimeError("cooldown service is stopping; new executor work is rejected")
        loop = asyncio.get_running_loop()
        operation = loop.run_in_executor(None, function, *args)
        owner = asyncio.create_task(
            settle_executor_operation(operation),
            name="cooldown-executor-owner",
        )
        self._executor_futures.add(owner)
        try:
            return await await_executor_owner(owner)
        finally:
            if owner.done():
                self._executor_futures.discard(owner)

    async def _consume_loop(self) -> None:
        """Читать показания из очереди брокера и обновлять буфер/детектор."""
        try:
            while self._running:
                try:
                    reading: Reading = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=5.0,
                    )
                except TimeoutError:
                    continue

                reading_ts = reading.timestamp.timestamp()
                self._last_reading_ts = reading_ts

                # NaN-доктрина: не годное показание (NaN/±inf или статус ошибки)
                # не попадает в детектор/буфер — staleness всё равно обновлён.
                if not reading.is_usable():
                    continue

                if reading.channel == self._channel_cold:
                    self._last_required_input_monotonic[self._channel_cold] = time.monotonic()
                    self._last_T_cold = reading.value
                    # Update detector (use reading timestamp for correct dT/dt)
                    self._detector.update(reading_ts, reading.value)
                elif reading.channel == self._channel_warm:
                    self._last_required_input_monotonic[self._channel_warm] = time.monotonic()
                    self._last_T_warm = reading.value

                # Buffer data during cooldown
                phase = self._detector.phase
                if phase in (CooldownPhase.COOLING, CooldownPhase.STABILIZING):
                    if self._cooldown_wall_start is None:
                        self._cooldown_wall_start = reading_ts

                    t_hours = (reading_ts - self._cooldown_wall_start) / 3600.0
                    T_cold = self._last_T_cold if self._last_T_cold is not None else float("nan")
                    T_warm = self._last_T_warm if self._last_T_warm is not None else float("nan")
                    self._buffer.append((t_hours, T_cold, T_warm))

                elif phase == CooldownPhase.COMPLETE:
                    await self._on_cooldown_end()

                elif phase == CooldownPhase.IDLE:
                    # Clear buffer if we're idle
                    if self._buffer:
                        self._buffer.clear()
                        self._cooldown_wall_start = None

        except asyncio.CancelledError:
            return

    async def _predict_loop(self) -> None:
        """Периодически вызывать predict() и публиковать DerivedMetric."""
        try:
            while self._running:
                await asyncio.sleep(self._predict_interval_s)
                await self._do_predict()
        except asyncio.CancelledError:
            return

    async def _do_predict(self) -> None:
        """Выполнить прогнозирование и опубликовать результат."""
        if self._model is None:
            return

        phase = self._detector.phase
        cooldown_active = phase in (CooldownPhase.COOLING, CooldownPhase.STABILIZING)

        T_cold = self._last_T_cold
        T_warm = self._last_T_warm
        if T_cold is None or T_warm is None:
            return
        freshness_horizon_s = max(3.0 * self._predict_interval_s, 1.0)
        now_monotonic = time.monotonic()
        required_channels = (self._channel_cold, self._channel_warm)
        if any(
            now_monotonic - self._last_required_input_monotonic.get(channel, float("-inf")) > freshness_horizon_s
            for channel in required_channels
        ):
            logger.warning("Cooldown prediction withheld because a required input is stale")
            return

        # Compute elapsed time
        # F-ReplayPredictor (v0.56.3): use the most recent reading timestamp
        # instead of time.time() so the predictor works under accelerated
        # replay (where readings stream faster than wall clock) AND under
        # live data (where reading_ts ≈ wall clock anyway). Mixing the two
        # clocks collapses the Gaussian weighting on t_at_p vs t_elapsed
        # at high replay speeds → predictor falls back to uniform weights
        # and emits trajectories anchored at "now" instead of the
        # accelerated timeline.
        if self._cooldown_wall_start is not None and cooldown_active and self._last_reading_ts is not None:
            t_elapsed = (self._last_reading_ts - self._cooldown_wall_start) / 3600.0
        else:
            t_elapsed = 0.0

        # Compute observed rates from buffer
        rate_cold: float | None = None
        rate_warm: float | None = None
        if len(self._buffer) >= 20:
            buf_arr = np.array(list(self._buffer))
            t_h = buf_arr[:, 0]
            Tc = buf_arr[:, 1]
            Tw = buf_arr[:, 2]
            rate_cold, rate_warm = compute_rate_from_history(
                t_h,
                Tc,
                Tw,
                window_h=self._rate_window_h,
            )

        # Run predict in executor (scipy is CPU-heavy)
        try:
            pred = await self._run_owned_executor(
                lambda: predict(
                    self._model,
                    T_cold,
                    T_warm,
                    t_elapsed=t_elapsed,
                    generate_trajectory=True,
                    observed_rate_cold=rate_cold,
                    observed_rate_warm=rate_warm,
                ),
            )
        except Exception as exc:
            logger.error("Ошибка прогнозирования охлаждения: %s", exc)
            return

        if not self._executor_admission_open:
            return

        # Build metadata
        metadata: dict[str, Any] = {
            "t_remaining_hours": pred.t_remaining_hours,
            "t_remaining_ci68": (pred.t_remaining_low_68, pred.t_remaining_high_68),
            "progress": pred.progress,
            "phase": pred.phase,
            "n_references": pred.n_references,
            "cooldown_active": cooldown_active,
            "cooldown_start_ts": self._detector.cooldown_start_ts or 0,
            "T_cold": T_cold,
            "T_warm": T_warm,
            "producer_interval_s": self._predict_interval_s,
        }
        self._last_prediction = metadata  # cache for F30 query agent
        # v0.55.3 — keep the raw dataclass so expected_value() can
        # interpolate future_t / future_T_cold_* without serialising
        # numpy arrays back from the metadata dict.
        self._last_prediction_raw = pred

        if pred.future_t is not None:
            metadata["future_t"] = pred.future_t.tolist()
            metadata["future_T_cold_mean"] = pred.future_T_cold_mean.tolist()
            metadata["future_T_cold_upper"] = pred.future_T_cold_upper.tolist()
            metadata["future_T_cold_lower"] = pred.future_T_cold_lower.tolist()

        # Publish DerivedMetric
        DerivedMetric.now(
            plugin_id="cooldown_predictor",
            metric="cooldown_eta",
            value=pred.t_remaining_hours,
            unit="h",
            metadata=metadata,
        )

        # Publish via broker to all subscribers
        reading = Reading.now(
            channel="analytics/cooldown_predictor/cooldown_eta",
            value=pred.t_remaining_hours,
            unit="h",
            instrument_id="cooldown_predictor",
            metadata=metadata | {"plugin_id": "cooldown_predictor"},
        )
        await self._broker.publish(reading)

        logger.debug(
            "Прогноз охлаждения: p=%.1f%%, осталось %.1f ч, фаза=%s",
            pred.progress * 100,
            pred.t_remaining_hours,
            pred.phase,
        )

    def _cooldown_cycle_ingest_identity(self) -> str:
        """Return one stable model-curve identity for the active cooldown."""

        started_at = self._detector.cooldown_start_ts
        if type(started_at) is not float:
            raise RuntimeError("completed cooldown has no stable start identity")
        if not math.isfinite(started_at) or started_at < 0.0 or started_at > 253_402_300_799.0:
            raise RuntimeError("completed cooldown start identity is invalid")
        started_at_us = int(round(started_at * 1_000_000.0))
        return f"auto_ingest_cycle_{started_at_us:020d}"

    def _load_reconciled_cycle_model(
        self,
        cycle_identity: str,
        source_digest: str,
    ) -> EnsembleModel | None:
        """Load only an exact cycle-identity and numeric-payload match."""

        model = load_model(self._model_dir)
        for curve in model.curves:
            if curve.name != cycle_identity:
                continue
            if getattr(curve, "source_digest", None) == source_digest:
                return model
            raise RuntimeError("cooldown cycle identity is bound to a different payload")
        return None

    def _ingest_completed_cycle(
        self,
        cycle_identity: str,
        t_hours: Any,
        T_cold: Any,
        T_warm: Any,
    ) -> tuple[bool, str, EnsembleModel | None]:
        """Commit or reconcile one idempotently named cooldown curve."""

        source_digest = cooldown_curve_source_digest(t_hours, T_cold, T_warm)
        try:
            result = ingest_from_raw_arrays(
                self._model_dir,
                t_hours,
                T_cold,
                T_warm,
                name=cycle_identity,
            )
        except Exception as ingest_error:
            try:
                reconciled = self._load_reconciled_cycle_model(
                    cycle_identity,
                    source_digest,
                )
            except Exception:
                raise ingest_error from None
            if reconciled is None:
                raise
            return True, f"already committed: '{cycle_identity}'", reconciled

        if result[0]:
            return result
        try:
            reconciled = self._load_reconciled_cycle_model(
                cycle_identity,
                source_digest,
            )
        except Exception:
            return result
        if reconciled is None:
            return result
        return True, f"already committed: '{cycle_identity}'", reconciled

    async def _on_cooldown_end(self) -> None:
        """Обработка завершения цикла охлаждения: auto-ingest."""
        if not self._buffer:
            logger.warning("Цикл охлаждения завершён, но буфер пуст")
            return

        buf_arr = np.array(list(self._buffer))
        t_hours = buf_arr[:, 0]
        T_cold = buf_arr[:, 1]
        T_warm = buf_arr[:, 2]

        duration_h = float(t_hours[-1])
        logger.info(
            "Цикл охлаждения завершён: %.1f ч, T_cold_final=%.2f K, %d точек",
            duration_h,
            float(T_cold[-1]),
            len(t_hours),
        )

        try:
            cycle_identity = self._cooldown_cycle_ingest_identity()
            source_digest = cooldown_curve_source_digest(t_hours, T_cold, T_warm)
        except Exception as exc:
            logger.error("Completed cooldown identity is not authoritative: %s", exc)
            return

        if self._auto_ingest and self._model is not None:
            if duration_h < self._min_cooldown_hours:
                logger.warning(
                    "Цикл слишком короткий для ingest: %.1f ч < %.1f ч",
                    duration_h,
                    self._min_cooldown_hours,
                )
            else:
                try:
                    ok, msg, new_model = await self._run_owned_executor(
                        self._ingest_completed_cycle,
                        cycle_identity,
                        t_hours,
                        T_cold,
                        T_warm,
                    )
                    if not self._executor_admission_open:
                        return
                    if ok and new_model is not None:
                        self._model = new_model
                        logger.info("Модель обновлена: %s", msg)
                    else:
                        logger.warning("Auto-ingest отклонён: %s", msg)
                        return
                except Exception as exc:
                    logger.error("Ошибка auto-ingest: %s", exc)
                    return

        # Task 8a: persist a cooldown fingerprint BEFORE clearing the buffer.
        # Flag-guarded, off hot-path, and never allowed to break cooldown-end
        # handling — the helper swallows and logs every error.
        # A2: enrich with ultimate_vacuum from the history reader (also
        # best-effort — any failure degrades to pressures=None).
        cfg = self._load_baseline_config()
        fingerprint_id: str | None = None
        if cfg.get("enabled", False):
            pressures = await self._read_cooldown_pressures(cfg)
            if not self._executor_admission_open:
                return
            fp = await self._run_owned_executor(
                self._persist_cooldown_fingerprint,
                t_hours,
                T_cold,
                pressures,
                cfg,
            )
            if not self._executor_admission_open:
                return
            if fp is not None:
                fingerprint_id = fp.fingerprint_id

        # Admit the identity-bound cooldown-end event before clearing any
        # authoritative cycle state. Publication failure is terminal for this
        # attempt and leaves the COMPLETE detector state and buffer retryable.
        try:
            published = await self._publish_cooldown_end_event(
                duration_h,
                float(T_cold[-1]),
                fingerprint_id,
                cycle_identity=cycle_identity,
                source_digest=source_digest,
            )
        except Exception as exc:
            logger.error("Cooldown-end publication did not settle: %s", exc)
            raise
        if published is False:
            return

        # Reset for next cycle
        self._buffer.clear()
        self._cooldown_wall_start = None
        self._detector.reset()

    async def _read_cooldown_pressures(self, cfg: dict[str, Any]) -> list[float] | None:
        """Best-effort: fetch the cooldown-window vacuum series. None on failure.

        Off the hot path (cooldown end is rare), so a full-window read via the
        reader's own executor is fine. Any error → None so the fingerprint tap
        simply stores a null ultimate_vacuum, as before A2.
        """
        reader = self._reader
        if reader is None:
            return None
        configured_channel = cfg.get("pressure_channel")
        if not isinstance(configured_channel, str) or not configured_channel.strip():
            logger.warning("Cooldown fingerprint pressure channel is not explicitly configured")
            return None
        channel = configured_channel.strip()
        try:
            hist = await reader.read_readings_history(
                channels=[channel],
                from_ts=self._detector.cooldown_start_ts,
                to_ts=self._last_reading_ts,
                limit_per_channel=100_000,
            )
            series = hist.get(channel) or []
            return [v for _, v in series] if series else None
        except Exception as exc:  # noqa: BLE001 — read must never break cooldown end
            logger.error("Ошибка чтения давления для fingerprint: %s", exc)
            return None

    async def _publish_cooldown_end_event(
        self,
        duration_h: float,
        T_cold_final: float,
        fingerprint_id: str | None,
        *,
        cycle_identity: str,
        source_digest: str,
    ) -> bool:
        """Publish one identity-bound ``cooldown_end`` event and report settlement."""

        if self._event_bus is None:
            raise RuntimeError("required cooldown-end EventBus target is unavailable")
        try:
            from cryodaq.core.event_bus import EngineEvent

            receipt = await self._event_bus.publish_required(
                EngineEvent(
                    event_type="cooldown_end",
                    timestamp=datetime.now(UTC),
                    payload={
                        "duration_h": duration_h,
                        "T_cold_final": T_cold_final,
                        "fingerprint_id": fingerprint_id,
                        "cycle_identity": cycle_identity,
                        "source_digest": source_digest,
                    },
                ),
                event_identity=cycle_identity,
                payload_digest=source_digest,
            )
            if not self._event_bus.validates_required_publication(
                receipt,
                event_identity=cycle_identity,
                payload_digest=source_digest,
            ):
                raise RuntimeError("cooldown-end EventBus admission receipt is invalid")
        except Exception as exc:  # noqa: BLE001 — required publication must fail closed
            logger.error("Ошибка публикации события cooldown_end: %s", exc)
            raise
        return True

    def _load_baseline_config(self) -> dict[str, Any]:
        """Load the ``cooldown_baseline`` block from plugins.yaml once.

        Cached on the instance. Returns an empty dict on any failure so the
        tap simply stays disabled.
        """
        if self._baseline_cfg is not None:
            return self._baseline_cfg
        cfg: dict[str, Any] = {}
        try:
            import yaml

            from cryodaq.paths import get_config_dir

            path = get_config_dir() / "plugins.yaml"
            if path.exists():
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                cfg = raw.get("cooldown_baseline", {}) or {}
        except Exception as exc:  # noqa: BLE001 — config read must never raise here
            logger.error("Ошибка чтения cooldown_baseline из plugins.yaml: %s", exc)
        self._baseline_cfg = cfg
        return cfg

    def _persist_cooldown_fingerprint(
        self,
        t_hours: Any,
        T_cold: Any,
        pressures: Any = None,
        cfg: dict[str, Any] | None = None,
    ) -> Any:
        """Best-effort: build + persist a cooldown fingerprint. Never raises.

        Returns the saved ``CooldownFingerprint`` (for the cooldown-end event
        payload), or ``None`` if disabled or on any error. ``pressures`` is the
        cold-window vacuum series wired via the history reader (A2); ``None``
        stores a null ultimate_vacuum, as before.
        """
        try:
            cfg = cfg if cfg is not None else self._load_baseline_config()
            if not cfg.get("enabled", False):
                return None

            from cryodaq.analytics.cooldown_fingerprint import (
                build_fingerprint,
                save_fingerprint,
            )
            from cryodaq.paths import get_data_dir

            fp = build_fingerprint(
                list(t_hours),
                list(T_cold),
                cooldown_start_ts=self._detector.cooldown_start_ts or 0.0,
                base_threshold_K=float(cfg.get("base_threshold_K", 5.0)),
                pressures=pressures,
            )
            history_dir = get_data_dir() / "cooldown_history"
            save_fingerprint(fp, history_dir)
            logger.info("Cooldown fingerprint сохранён: %s", fp.fingerprint_id)
            return fp
        except Exception as exc:  # noqa: BLE001 — tap must never break cooldown end
            logger.error("Ошибка сохранения cooldown fingerprint: %s", exc)
            return None
