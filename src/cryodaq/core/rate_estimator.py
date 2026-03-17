"""RateEstimator — оценка dX/dt методом OLS линейной регрессии по скользящему окну.

Почему не конечная разность:
  При разрешении LS218 ±0.01 K и интервале 0.5 с конечная разность даёт шум
  ±2.4 K/мин — сравнимо с порогом 5 K/мин. Линейная регрессия по 120 с
  (240 точек) даёт стабильную оценку с погрешностью < 0.1 K/мин.
"""

from __future__ import annotations

import math
from collections import deque


class RateEstimator:
    """Оценка скорости изменения dX/dt для каждого канала.

    Метод: OLS линейная регрессия по скользящему окну.
    Результат: unit/мин (K/мин для температур, mbar/мин для давления).

    Параметры
    ----------
    window_s:
        Ширина скользящего окна в секундах. По умолчанию 120 с.
    min_points:
        Минимальное число точек для вычисления rate. По умолчанию 60.
    """

    def __init__(self, window_s: float = 120.0, min_points: int = 60) -> None:
        self._window_s = window_s
        self._min_points = min_points
        # channel → deque of (timestamp_s, value)
        self._buffers: dict[str, deque[tuple[float, float]]] = {}

    def push(self, channel: str, timestamp: float, value: float) -> None:
        """Добавить точку. Автоматически удаляет точки старше окна."""
        buf = self._buffers.setdefault(channel, deque(maxlen=5000))
        buf.append((timestamp, value))
        cutoff = timestamp - self._window_s
        while buf and buf[0][0] < cutoff:
            buf.popleft()

    def get_rate(self, channel: str) -> float | None:
        """Вернуть dX/dt в единицах [unit/мин]. None если недостаточно данных."""
        buf = self._buffers.get(channel)
        if not buf or len(buf) < self._min_points:
            return None
        return _ols_slope_per_min(list(buf))

    def get_rate_custom_window(self, channel: str, window_s: float) -> float | None:
        """dX/dt с нестандартным окном (например vacuum_loss_early: 60 с).

        Использует самые свежие точки в пределах `window_s` из буфера канала.
        Требует min_points точек в этом окне.
        """
        buf = self._buffers.get(channel)
        if not buf:
            return None
        latest_ts = buf[-1][0]
        cutoff = latest_ts - window_s
        points = [(t, v) for t, v in buf if t >= cutoff]
        if len(points) < self._min_points:
            return None
        return _ols_slope_per_min(points)

    def channels(self) -> list[str]:
        """Список каналов с данными."""
        return list(self._buffers.keys())

    def buffer_size(self, channel: str) -> int:
        """Размер буфера для канала (для диагностики)."""
        buf = self._buffers.get(channel)
        return len(buf) if buf else 0


def _ols_slope_per_min(points: list[tuple[float, float]]) -> float | None:
    """Вычислить OLS slope в unit/мин.

    slope_per_sec = Σ((t-t̄)(v-v̄)) / Σ((t-t̄)²)
    result = slope_per_sec * 60

    Возвращает None если знаменатель нулевой (все t одинаковы).
    """
    n = len(points)
    if n < 2:
        return None

    # Нормализуем время относительно первой точки для численной стабильности
    t0 = points[0][0]
    ts = [t - t0 for t, _ in points]
    vs = [v for _, v in points]

    t_mean = sum(ts) / n
    v_mean = sum(vs) / n

    num = sum((t - t_mean) * (v - v_mean) for t, v in zip(ts, vs))
    den = sum((t - t_mean) ** 2 for t in ts)

    if den == 0.0 or math.isnan(den) or math.isnan(num):
        return None

    slope_per_sec = num / den
    return slope_per_sec * 60.0  # → unit/мин
