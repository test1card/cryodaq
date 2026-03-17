"""ChannelStateTracker — хранит текущее состояние каналов для alarm evaluator.

Отслеживает свежесть данных (stale detection) и накапливает историю fault
readings для intermittent fault detection.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryodaq.drivers.base import Reading

# Fault: значение за пределами физически допустимого диапазона температур
_FAULT_MIN = 0.0    # K
_FAULT_MAX = 350.0  # K


@dataclass
class ChannelState:
    """Текущее состояние канала измерения."""

    channel: str
    value: float
    timestamp: float          # unix timestamp
    unit: str
    instrument_id: str
    is_stale: bool = False
    fault_count_window: int = 0  # количество fault readings в окне (заполняется трекером)


class ChannelStateTracker:
    """Отслеживает текущее состояние всех каналов.

    Параметры
    ----------
    stale_timeout_s:
        Время без обновления, после которого канал считается устаревшим.
    fault_window_s:
        Окно (в секундах) для подсчёта fault readings.
    """

    def __init__(
        self,
        stale_timeout_s: float = 30.0,
        fault_window_s: float = 300.0,
    ) -> None:
        self._stale_timeout = stale_timeout_s
        self._fault_window = fault_window_s
        self._states: dict[str, ChannelState] = {}
        # channel → deque of fault timestamps (unix)
        self._fault_history: dict[str, deque[float]] = {}

    def update(self, reading: Reading) -> None:
        """Обновить состояние канала из нового Reading.

        Если значение выходит за пределы [0, 350] K (для температурных каналов),
        регистрирует fault.
        """
        ts = reading.timestamp.timestamp()
        state = ChannelState(
            channel=reading.channel,
            value=reading.value,
            timestamp=ts,
            unit=reading.unit,
            instrument_id=reading.instrument_id,
            is_stale=False,
        )
        self._states[reading.channel] = state

        # Fault detection: только для temperature channels (unit == "K")
        if reading.unit == "K":
            if reading.value < _FAULT_MIN or reading.value > _FAULT_MAX:
                self.record_fault(reading.channel, ts)

        # Обновляем fault_count в state
        state.fault_count_window = self.get_fault_count(reading.channel)

    def get(self, channel: str) -> ChannelState | None:
        """Текущее состояние канала. None если нет данных."""
        state = self._states.get(channel)
        if state is None:
            return None
        # Обновляем is_stale на момент запроса
        state.is_stale = (time.time() - state.timestamp) > self._stale_timeout
        state.fault_count_window = self.get_fault_count(channel)
        return state

    def get_stale_channels(self, timeout_s: float | None = None) -> list[str]:
        """Каналы без обновлений дольше timeout_s (или stale_timeout_s по умолчанию)."""
        threshold = timeout_s if timeout_s is not None else self._stale_timeout
        now = time.time()
        return [
            ch for ch, st in self._states.items()
            if (now - st.timestamp) > threshold
        ]

    def record_fault(self, channel: str, timestamp: float) -> None:
        """Записать fault reading для intermittent fault detection."""
        hist = self._fault_history.setdefault(channel, deque())
        hist.append(timestamp)
        # Удалить устаревшие записи
        cutoff = timestamp - self._fault_window
        while hist and hist[0] < cutoff:
            hist.popleft()

    def get_fault_count(self, channel: str) -> int:
        """Количество fault readings в текущем окне fault_window_s."""
        hist = self._fault_history.get(channel)
        if not hist:
            return 0
        cutoff = time.time() - self._fault_window
        # Trim expired entries
        while hist and hist[0] < cutoff:
            hist.popleft()
        return len(hist)

    def channels(self) -> list[str]:
        """Список каналов с данными."""
        return list(self._states.keys())
