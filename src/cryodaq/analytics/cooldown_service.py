"""Сервис прогнозирования охлаждения для CryoDAQ Engine.

Интегрирует cooldown_predictor с DataBroker:
- CooldownDetector: определяет начало/конец цикла охлаждения
- CooldownService: asyncio-сервис, подписывается на брокер,
  периодически вызывает predict(), публикует DerivedMetric
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from cryodaq.analytics.base_plugin import DerivedMetric
from cryodaq.analytics.cooldown_predictor import (
    EnsembleModel,
    PredictionResult,
    compute_rate_from_history,
    ingest_from_raw_arrays,
    load_model,
    predict,
)
from cryodaq.analytics.steady_state import SteadyStatePredictor
from cryodaq.core.broker import DataBroker
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
    ) -> None:
        self._broker = broker
        self._config = config
        self._model_dir = model_dir

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

        # Queue & tasks
        self._queue: asyncio.Queue | None = None
        self._consume_task: asyncio.Task | None = None
        self._predict_task: asyncio.Task | None = None
        self._running = False

        # Latest T values for detector
        self._last_T_cold: float | None = None
        self._last_T_warm: float | None = None

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

    def expected_value(
        self, channel: str, ts_monotonic: float
    ) -> tuple[float, float] | None:
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

    async def start(self) -> None:
        """Запустить сервис: подписка на брокер, загрузка модели, запуск задач."""
        if self._running:
            return

        channels = {self._channel_cold, self._channel_warm}

        def _filter(reading: Reading) -> bool:
            return reading.channel in channels

        self._queue = await self._broker.subscribe(
            "cooldown_service",
            maxsize=5000,
            filter_fn=_filter,
        )

        # Load model (in executor, may be slow)
        loop = asyncio.get_running_loop()
        try:
            model_file = self._model_dir / "predictor_model.json"
            if model_file.exists():
                self._model = await loop.run_in_executor(None, load_model, self._model_dir)
                logger.info(
                    "Модель охлаждения загружена: %d кривых, %.1f +/- %.1f ч",
                    self._model.n_curves,
                    self._model.duration_mean,
                    self._model.duration_std,
                )
            else:
                logger.warning(
                    "Файл модели не найден: %s — прогнозирование недоступно",
                    model_file,
                )
        except Exception as exc:
            logger.error("Ошибка загрузки модели охлаждения: %s", exc)

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
        """Остановить сервис: отмена задач, отписка от брокера."""
        if not self._running:
            return
        self._running = False

        for task in (self._consume_task, self._predict_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await self._broker.unsubscribe("cooldown_service")
        logger.info("CooldownService остановлен")

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
                    self._last_T_cold = reading.value
                    # Update detector (use reading timestamp for correct dT/dt)
                    self._detector.update(reading_ts, reading.value)
                elif reading.channel == self._channel_warm:
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

        # Compute elapsed time
        # F-ReplayPredictor (v0.56.3): use the most recent reading timestamp
        # instead of time.time() so the predictor works under accelerated
        # replay (where readings stream faster than wall clock) AND under
        # live data (where reading_ts ≈ wall clock anyway). Mixing the two
        # clocks collapses the Gaussian weighting on t_at_p vs t_elapsed
        # at high replay speeds → predictor falls back to uniform weights
        # and emits trajectories anchored at "now" instead of the
        # accelerated timeline.
        if (
            self._cooldown_wall_start is not None
            and cooldown_active
            and self._last_reading_ts is not None
        ):
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
        loop = asyncio.get_running_loop()
        try:
            pred = await loop.run_in_executor(
                None,
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

    async def _on_cooldown_end(self) -> None:
        """Обработка завершения цикла охлаждения: auto-ingest."""
        if not self._buffer:
            logger.warning("Цикл охлаждения завершён, но буфер пуст")
            self._detector.reset()
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

        if self._auto_ingest and self._model is not None:
            if duration_h < self._min_cooldown_hours:
                logger.warning(
                    "Цикл слишком короткий для ingest: %.1f ч < %.1f ч",
                    duration_h,
                    self._min_cooldown_hours,
                )
            else:
                loop = asyncio.get_running_loop()
                try:
                    ok, msg, new_model = await loop.run_in_executor(
                        None,
                        lambda: ingest_from_raw_arrays(
                            self._model_dir,
                            t_hours,
                            T_cold,
                            T_warm,
                        ),
                    )
                    if ok and new_model is not None:
                        self._model = new_model
                        logger.info("Модель обновлена: %s", msg)
                    else:
                        logger.warning("Auto-ingest отклонён: %s", msg)
                except Exception as exc:
                    logger.error("Ошибка auto-ingest: %s", exc)

        # Task 8a: persist a cooldown fingerprint BEFORE clearing the buffer.
        # Flag-guarded, off hot-path, and never allowed to break cooldown-end
        # handling — the helper swallows and logs every error.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            self._persist_cooldown_fingerprint,
            t_hours,
            T_cold,
        )

        # Reset for next cycle
        self._buffer.clear()
        self._cooldown_wall_start = None
        self._detector.reset()

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

    def _persist_cooldown_fingerprint(self, t_hours: Any, T_cold: Any) -> None:
        """Best-effort: build + persist a cooldown fingerprint. Never raises.

        Vacuum enrichment (ultimate_vacuum) is left null here: the service has
        no SQLite reader handle, and wiring one requires touching engine
        construction (out of scope for this backend task). ``build_fingerprint``
        accepts a ``pressures`` series, so the capability is available for a
        later off-hot-path enrichment.
        """
        try:
            cfg = self._load_baseline_config()
            if not cfg.get("enabled", False):
                return

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
                pressures=None,
            )
            history_dir = get_data_dir() / "cooldown_history"
            save_fingerprint(fp, history_dir)
            logger.info("Cooldown fingerprint сохранён: %s", fp.fingerprint_id)
        except Exception as exc:  # noqa: BLE001 — tap must never break cooldown end
            logger.error("Ошибка сохранения cooldown fingerprint: %s", exc)
