"""Плагин прогнозирования времени охлаждения для CryoDAQ.

Аппроксимирует экспоненциальный спад температуры T(t) = T_base + A·exp(-t/τ)
по скользящему окну данных и вычисляет ожидаемое время достижения целевой
температуры.  Использует только стандартную библиотеку Python (math, statistics,
collections) — зависимость от numpy/scipy отсутствует.

Метод подгонки: log-линейная регрессия
    ln(T(t) - T_base) = ln(A) - t/τ
    ↓
    y_i = ln(T_i - T_base),  x_i = t_i  →  линейная регрессия y = b + k·x
    τ = -1/k,  A = exp(b)
"""

from __future__ import annotations

import logging
import math
from collections import deque
from datetime import datetime, timezone
from statistics import linear_regression
from typing import Any

from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric
from cryodaq.drivers.base import ChannelStatus, Reading

_log = logging.getLogger(__name__)

# Минимальное количество точек для выполнения регрессии
_MIN_FIT_POINTS = 10

# Запас ниже минимума при оценке T_base (доля от min(T))
_T_BASE_MARGIN = 0.9


class CooldownEstimator(AnalyticsPlugin):
    """Оценка оставшегося времени охлаждения по экспоненциальному спаду.

    Накапливает показания целевого канала в скользящем временном окне
    и аппроксимирует их функцией::

        T(t) = T_base + A · exp(-t / τ)

    Аппроксимация выполняется методом log-линейной регрессии без numpy/scipy.

    Конфигурация (YAML):
        target_channel (str):   Имя канала температуры для отслеживания.
        target_T (float):       Целевая температура (К).
        fit_window_s (float):   Ширина скользящего окна (с), по умолчанию 600.

    Возвращаемая метрика:
        ``"cooldown_eta_s"`` — оценка оставшегося времени (с).

    Ограничения:
        - Менее 10 точек в окне → пустой список.
        - Температура растёт → пустой список.
        - T_base ≥ target_T → пустой список (уже достигнуто или невозможно).
        - Отрицательное или нефинитное время → пустой список.
    """

    plugin_id = "cooldown_estimator"

    def __init__(self) -> None:
        """Инициализировать плагин с пустым состоянием."""
        super().__init__(self.plugin_id)

        self._target_channel: str = ""
        self._target_T: float = 4.2
        self._fit_window_s: float = 600.0

        # Скользящее окно: deque[(timestamp_s: float, T: float)]
        # Максимальный размер deque не ограничиваем по количеству записей —
        # удаление старых точек выполняется явно по времени в process().
        self._buffer: deque[tuple[float, float]] = deque()

    # ------------------------------------------------------------------
    # Конфигурация
    # ------------------------------------------------------------------

    def configure(self, config: dict[str, Any]) -> None:
        """Применить конфигурацию плагина.

        Ожидаемые ключи:
            target_channel (str):   Имя канала температуры.
            target_T (float):       Целевая температура в Кельвинах.
            fit_window_s (float):   Ширина окна для подгонки (с); по умолчанию 600.

        Аргументы:
            config: Словарь параметров из YAML-файла.
        """
        super().configure(config)

        self._target_channel = str(config.get("target_channel", ""))

        raw_target = config.get("target_T", 4.2)
        try:
            self._target_T = float(raw_target)
        except (TypeError, ValueError):
            _log.warning(
                "CooldownEstimator: некорректное значение target_T=%r, "
                "используется 4.2 K",
                raw_target,
            )
            self._target_T = 4.2

        raw_window = config.get("fit_window_s", 600.0)
        try:
            self._fit_window_s = float(raw_window)
            if self._fit_window_s <= 0:
                raise ValueError("fit_window_s должно быть положительным")
        except (TypeError, ValueError):
            _log.warning(
                "CooldownEstimator: некорректное значение fit_window_s=%r, "
                "используется 600 с",
                raw_window,
            )
            self._fit_window_s = 600.0

        # Сбросить буфер при переконфигурации
        self._buffer.clear()

        _log.info(
            "CooldownEstimator сконфигурирован: канал=%r, цель=%.4f K, окно=%.1f с",
            self._target_channel,
            self._target_T,
            self._fit_window_s,
        )

    # ------------------------------------------------------------------
    # Основная логика
    # ------------------------------------------------------------------

    async def process(self, readings: list[Reading]) -> list[DerivedMetric]:
        """Обработать пакет показаний и вернуть прогноз времени охлаждения.

        Алгоритм:
            1. Отфильтровать показания по ``target_channel`` (статус OK).
            2. Добавить в скользящий буфер; удалить устаревшие точки.
            3. При наличии не менее 10 точек выполнить log-линейную регрессию.
            4. Проверить условия монотонности и достижимости цели.
            5. Вычислить оставшееся время и вернуть метрику.

        Аргументы:
            readings: Список показаний за текущий интервал опроса.

        Возвращает:
            Список из одного :class:`~cryodaq.analytics.base_plugin.DerivedMetric`
            с метрикой ``"cooldown_eta_s"`` (с), либо пустой список.
        """
        if not self._target_channel:
            _log.warning(
                "CooldownEstimator: target_channel не задан, вычисление пропущено"
            )
            return []

        # --- 1. Фильтрация и добавление в буфер ---
        relevant = [
            r
            for r in readings
            if r.channel == self._target_channel and r.status is ChannelStatus.OK
        ]
        relevant.sort(key=lambda r: r.timestamp)

        for reading in relevant:
            t_s = reading.timestamp.timestamp()
            self._buffer.append((t_s, reading.value))

        if not self._buffer:
            return []

        # --- 2. Удаление устаревших точек ---
        t_now = datetime.now(timezone.utc).timestamp()
        t_cutoff = t_now - self._fit_window_s
        while self._buffer and self._buffer[0][0] < t_cutoff:
            self._buffer.popleft()

        n = len(self._buffer)
        if n < _MIN_FIT_POINTS:
            _log.debug(
                "CooldownEstimator: недостаточно точек в окне (%d < %d)",
                n,
                _MIN_FIT_POINTS,
            )
            return []

        times = [pt[0] for pt in self._buffer]
        temps = [pt[1] for pt in self._buffer]

        current_T = temps[-1]

        # --- 3. Проверка на охлаждение (температура должна убывать) ---
        # Используем первую и последнюю точку окна как грубую оценку тренда.
        if temps[-1] >= temps[0]:
            _log.debug(
                "CooldownEstimator: температура не убывает "
                "(начало=%.4f K, конец=%.4f K), прогноз не выполняется",
                temps[0],
                temps[-1],
            )
            return []

        # --- 4. Оценка T_base ---
        # T_base — асимптотическая температура равновесия.
        # Берём минимум из: (минимальное измеренное значение) * 0.9 и target_T.
        T_min = min(temps)
        T_base = min(T_min * _T_BASE_MARGIN, self._target_T)

        # Проверить, что текущая температура ещё выше цели
        if current_T <= self._target_T:
            _log.debug(
                "CooldownEstimator: текущая температура %.4f K уже достигла "
                "цели %.4f K",
                current_T,
                self._target_T,
            )
            return []

        # --- 5. Log-линейная регрессия ---
        # Преобразование: y_i = ln(T_i - T_base)
        # Фильтруем точки, где T_i > T_base (логарифм определён)
        xs: list[float] = []
        ys: list[float] = []
        for t_s, T in zip(times, temps):
            diff = T - T_base
            if diff <= 0.0:
                # Точка лежит ниже или на уровне T_base — пропустить
                continue
            xs.append(t_s)
            ys.append(math.log(diff))

        if len(xs) < _MIN_FIT_POINTS:
            _log.debug(
                "CooldownEstimator: после фильтрации T > T_base осталось "
                "менее %d точек (%d), прогноз пропущен",
                _MIN_FIT_POINTS,
                len(xs),
            )
            return []

        # Нормируем время относительно первой точки для численной устойчивости
        t0 = xs[0]
        xs_norm = [x - t0 for x in xs]

        try:
            slope, intercept = linear_regression(xs_norm, ys)
        except Exception as exc:
            _log.warning(
                "CooldownEstimator: ошибка линейной регрессии: %s", exc
            )
            return []

        # slope = -1/tau  →  tau = -1/slope
        if slope >= 0.0:
            _log.debug(
                "CooldownEstimator: наклон регрессии ≥ 0 (slope=%.6g), "
                "температура не убывает экспоненциально",
                slope,
            )
            return []

        tau = -1.0 / slope          # постоянная времени (с), > 0
        A = math.exp(intercept)     # амплитуда при t = t0

        # --- 6. Оценка оставшегося времени ---
        # T(t) = T_base + A·exp(-t/tau) = target_T
        # t_remaining (от t0) = -tau · ln((target_T - T_base) / A)
        target_diff = self._target_T - T_base
        if target_diff <= 0.0:
            _log.debug(
                "CooldownEstimator: T_base=%.4f K ≥ target_T=%.4f K, "
                "прогноз невозможен",
                T_base,
                self._target_T,
            )
            return []

        ratio = target_diff / A
        if ratio <= 0.0 or ratio >= 1.0:
            # ratio >= 1 означает, что цель уже ниже T_base + A (нереалистично)
            _log.debug(
                "CooldownEstimator: отношение (target_T - T_base)/A = %.6g "
                "вне допустимого диапазона (0, 1)",
                ratio,
            )
            return []

        t_target_from_t0 = -tau * math.log(ratio)
        t_now_from_t0 = t_now - t0
        t_remaining = t_target_from_t0 - t_now_from_t0

        if not math.isfinite(t_remaining) or t_remaining < 0.0:
            _log.debug(
                "CooldownEstimator: вычисленное оставшееся время %.2f с "
                "недопустимо (< 0 или нефинитно)",
                t_remaining,
            )
            return []

        _log.debug(
            "CooldownEstimator: tau=%.1f с, A=%.4f, T_base=%.4f K, "
            "T_текущая=%.4f K, цель=%.4f K → ETA=%.1f с",
            tau,
            A,
            T_base,
            current_T,
            self._target_T,
            t_remaining,
        )

        return [
            DerivedMetric.now(
                self.plugin_id,
                "cooldown_eta_s",
                t_remaining,
                "s",
                metadata={
                    "tau": tau,
                    "A": A,
                    "T_base": T_base,
                    "current_T": current_T,
                    "target_T": self._target_T,
                    "fit_points": len(xs),
                    "fit_window_s": self._fit_window_s,
                },
            )
        ]
