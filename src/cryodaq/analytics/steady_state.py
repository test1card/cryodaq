"""Предсказатель стационарного состояния температуры.

Аппроксимирует T(t) = T_inf + A * exp(-t/tau) по скользящему окну данных,
предсказывает стационарную температуру T_inf и оценивает степень
стабилизации (percent_settled).
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Минимум точек и времени для начала предсказания
_MIN_POINTS = 30
_MIN_DURATION_S = 60.0
# Минимальный |dT/dt| для признания процесса нестационарным (К/мин)
_MIN_RATE = 0.001


@dataclass(frozen=True, slots=True)
class SteadyStatePrediction:
    """Результат предсказания стационарного состояния."""

    channel: str
    t_predicted: float  # T_inf — предсказанная стационарная температура (К)
    t_current: float  # Текущая температура (К)
    tau_s: float  # Постоянная времени (секунды)
    amplitude: float  # A — амплитуда экспоненты
    percent_settled: float  # 0–100%: степень стабилизации
    confidence: float  # Относительная ошибка аппроксимации (0–1)
    valid: bool  # Достаточно ли данных для прогноза


class SteadyStatePredictor:
    """Предсказатель стационарного состояния.

    Для каждого отслеживаемого канала накапливает данные в скользящем окне
    и выполняет curve_fit каждые ``update_interval_s`` секунд.

    Параметры
    ----------
    window_s:  Ширина скользящего окна данных (секунды).
    update_interval_s:  Минимальный интервал между пересчётами.
    """

    def __init__(self, *, window_s: float = 300.0, update_interval_s: float = 10.0) -> None:
        self._window_s = window_s
        self._update_interval_s = update_interval_s

        # channel → deque[(ts_s, value)]
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        # channel → последний результат
        self._predictions: dict[str, SteadyStatePrediction] = {}
        # channel → время последнего пересчёта
        self._last_update: dict[str, float] = {}

    def add_point(self, channel: str, ts: float, value: float) -> None:
        """Добавить точку данных."""
        if channel not in self._buffers:
            maxlen = int(self._window_s * 4) + 100  # запас для 0.5с опроса
            self._buffers[channel] = deque(maxlen=maxlen)
        self._buffers[channel].append((ts, value))

    def get_prediction(self, channel: str) -> SteadyStatePrediction | None:
        """Получить последнее предсказание для канала."""
        return self._predictions.get(channel)

    def get_all_predictions(self) -> dict[str, SteadyStatePrediction]:
        """Получить все предсказания."""
        return dict(self._predictions)

    def update(self, now: float) -> dict[str, SteadyStatePrediction]:
        """Пересчитать предсказания для каналов, которые готовы к обновлению.

        Возвращает словарь обновлённых предсказаний.
        """
        updated: dict[str, SteadyStatePrediction] = {}

        for channel, buf in self._buffers.items():
            last = self._last_update.get(channel, 0.0)
            if now - last < self._update_interval_s:
                continue

            # Очистить старые точки
            cutoff = now - self._window_s
            while buf and buf[0][0] < cutoff:
                buf.popleft()

            if len(buf) < _MIN_POINTS:
                self._predictions[channel] = SteadyStatePrediction(
                    channel=channel,
                    t_predicted=0.0,
                    t_current=buf[-1][1] if buf else 0.0,
                    tau_s=0.0,
                    amplitude=0.0,
                    percent_settled=0.0,
                    confidence=0.0,
                    valid=False,
                )
                continue

            duration = buf[-1][0] - buf[0][0]
            if duration < _MIN_DURATION_S:
                continue

            # Проверить, что идёт процесс (|dT/dt| > порог)
            v_first, v_last = buf[0][1], buf[-1][1]
            rate_k_min = abs(v_last - v_first) / (duration / 60.0) if duration > 0 else 0

            pred = self._fit_exponential(channel, buf, rate_k_min)
            self._predictions[channel] = pred
            self._last_update[channel] = now
            updated[channel] = pred

        return updated

    def _fit_exponential(
        self,
        channel: str,
        buf: deque[tuple[float, float]],
        rate: float,
    ) -> SteadyStatePrediction:
        """Выполнить аппроксимацию T(t) = T_inf + A * exp(-t/tau)."""
        t_current = buf[-1][1]

        # Если скорость слишком мала — уже стационар
        if rate < _MIN_RATE:
            return SteadyStatePrediction(
                channel=channel,
                t_predicted=t_current,
                t_current=t_current,
                tau_s=0.0,
                amplitude=0.0,
                percent_settled=100.0,
                confidence=1.0,
                valid=True,
            )

        try:
            from scipy.optimize import curve_fit
        except ImportError:
            logger.warning("scipy не установлен — предсказание недоступно")
            return SteadyStatePrediction(
                channel=channel,
                t_predicted=t_current,
                t_current=t_current,
                tau_s=0.0,
                amplitude=0.0,
                percent_settled=0.0,
                confidence=0.0,
                valid=False,
            )

        # Подготовить данные
        t0 = buf[0][0]
        xs = [pt[0] - t0 for pt in buf]
        ys = [pt[1] for pt in buf]

        # Начальные приближения
        T_inf_guess = ys[-1]
        A_guess = ys[0] - ys[-1]
        tau_guess = (xs[-1] - xs[0]) / 3.0 if xs[-1] > xs[0] else 60.0

        def exp_model(t: float, T_inf: float, A: float, tau: float) -> float:
            return T_inf + A * math.exp(-t / tau) if tau > 0 else T_inf

        try:
            # Векторизация для curve_fit
            import numpy as np

            xs_arr = np.array(xs)
            ys_arr = np.array(ys)

            def model_vec(t: np.ndarray, T_inf: float, A: float, tau: float) -> np.ndarray:
                return T_inf + A * np.exp(-t / max(tau, 0.01))

            popt, pcov = curve_fit(
                model_vec,
                xs_arr,
                ys_arr,
                p0=[T_inf_guess, A_guess, max(tau_guess, 1.0)],
                maxfev=2000,
                bounds=(
                    [0.0, -1000.0, 0.1],  # нижние границы (T≥0K)
                    [500.0, 1000.0, 100000.0],  # верхние границы
                ),
            )
            T_inf, A, tau = popt

            # Оценка ошибки
            residuals = ys_arr - model_vec(xs_arr, *popt)
            rmse = float(np.sqrt(np.mean(residuals**2)))
            y_range = max(ys) - min(ys) if max(ys) != min(ys) else 1.0
            confidence = max(0.0, 1.0 - rmse / y_range)

            # Процент стабилизации
            if abs(A) > 1e-10:
                settled = 100.0 * (1.0 - abs(t_current - T_inf) / abs(A))
                settled = max(0.0, min(100.0, settled))
            else:
                settled = 100.0

            return SteadyStatePrediction(
                channel=channel,
                t_predicted=float(T_inf),
                t_current=t_current,
                tau_s=float(tau),
                amplitude=float(A),
                percent_settled=settled,
                confidence=confidence,
                valid=True,
            )

        except Exception as exc:
            logger.debug("curve_fit для '%s' не сошёлся: %s", channel, exc)
            return SteadyStatePrediction(
                channel=channel,
                t_predicted=t_current,
                t_current=t_current,
                tau_s=0.0,
                amplitude=0.0,
                percent_settled=0.0,
                confidence=0.0,
                valid=False,
            )
