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
    min_span_s:
        Минимальный временной охват данных (buf[-1].t − buf[0].t) для
        вычисления rate. None (по умолчанию) — гейт только по min_points.
        Задаёт poll-rate-независимый гейт: rate появляется после
        min_span_s секунд данных независимо от интервала опроса.
    """

    def __init__(
        self,
        window_s: float = 120.0,
        min_points: int = 60,
        min_span_s: float | None = None,
    ) -> None:
        self._window_s = window_s
        self._min_points = min_points
        self._min_span_s = min_span_s
        # Safety cap: 2× window at 10 Hz + 100 margin.
        # Prevents unbounded growth if trim lags; actual usage is window_s × sample_rate.
        self._maxlen: int = max(500, int(window_s * 20) + 100)
        # channel → deque of (timestamp_s, value)
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        # short prefix → full channel name (e.g. "Т12" → "Т12 Теплообменник 2")
        self._short_to_full: dict[str, str] = {}

    def push(self, channel: str, timestamp: float, value: float) -> None:
        """Добавить точку. Автоматически удаляет точки старше окна."""
        buf = self._buffers.setdefault(channel, deque(maxlen=self._maxlen))
        buf.append((timestamp, value))
        cutoff = timestamp - self._window_s
        while buf and buf[0][0] < cutoff:
            buf.popleft()
        # Build short→full index for prefix resolution
        short = channel.split(" ", 1)[0] if " " in channel else channel
        if short != channel:
            self._short_to_full[short] = channel

    def resolve_channel(self, channel: str) -> str:
        """Resolve short channel ID to full runtime name."""
        if channel in self._buffers:
            return channel
        return self._short_to_full.get(channel, channel)

    def get_rate(self, channel: str) -> float | None:
        """Вернуть dX/dt в единицах [unit/мин]. None если недостаточно данных."""
        channel = self.resolve_channel(channel)
        buf = self._buffers.get(channel)
        if not buf or len(buf) < self._min_points:
            return None
        if self._min_span_s is not None and buf[-1][0] - buf[0][0] < self._min_span_s:
            return None
        return _ols_slope_per_min(list(buf))

    def get_rate_custom_window(self, channel: str, window_s: float) -> float | None:
        """dX/dt с нестандартным окном (например vacuum_loss_early: 60 с).

        Использует самые свежие точки в пределах `window_s` из буфера канала.
        Требует min_points точек в этом окне.
        """
        channel = self.resolve_channel(channel)
        buf = self._buffers.get(channel)
        if not buf:
            return None
        latest_ts = buf[-1][0]
        cutoff = latest_ts - window_s
        points = [(t, v) for t, v in buf if t >= cutoff]
        if len(points) < self._min_points:
            return None
        if self._min_span_s is not None and points[-1][0] - points[0][0] < self._min_span_s:
            return None
        return _ols_slope_per_min(points)

    def channels(self) -> list[str]:
        """Список каналов с данными."""
        return list(self._buffers.keys())

    def buffer_size(self, channel: str) -> int:
        """Размер буфера для канала (для диагностики)."""
        channel = self.resolve_channel(channel)
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

    # DOMAIN guard, not a validity guard: den==0 → all timestamps equal
    # (undefined slope); isnan(num/den) → numeric propagation. Validity of
    # readings is decided upstream at the Reading boundary (NaN-доктрина);
    # this stays as the OLS division-domain floor.
    if den == 0.0 or math.isnan(den) or math.isnan(num):
        return None

    slope_per_sec = num / den
    return slope_per_sec * 60.0  # → unit/мин
