"""Сервис прогнозирования охлаждения для CryoDAQ Engine.

Интегрирует cooldown_predictor с DataBroker:
- CooldownDetector: определяет начало/конец цикла охлаждения
- CooldownService: asyncio-сервис, подписывается на брокер,
  периодически вызывает predict(), публикует DerivedMetric
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from cryodaq.analytics.base_plugin import DerivedMetric
from cryodaq.analytics.cooldown_predictor import (
    EnsembleModel,
    compute_rate_from_history,
    ingest_from_raw_arrays,
    load_model,
    predict,
)
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

    @property
    def phase(self) -> CooldownPhase:
        return self._detector.phase

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
        if self._cooldown_wall_start is not None and cooldown_active:
            t_elapsed = (time.time() - self._cooldown_wall_start) / 3600.0
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
        }

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

        # Reset for next cycle
        self._buffer.clear()
        self._cooldown_wall_start = None
        self._detector.reset()
