"""Per-channel reading history storage for the new dashboard.

Owned by DashboardView. Plot widgets, sensor cards, and phase-aware
widgets all read from this single source instead of duplicating
buffers across components.

Buffer maxlen matches the legacy OverviewPanel value (24 hours at
1 Hz nominal) — enough history for the longest time window option
('Всё' acts as 'show whole buffer').
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

# 1 Hz nominal × 24 hours = 86400 samples per channel.
_BUFFER_MAXLEN = 86400


class ChannelBufferStore:
    """Rolling per-channel deque store with last-value lookup."""

    def __init__(self, maxlen: int = _BUFFER_MAXLEN) -> None:
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        self._last_value: dict[str, tuple[float, float]] = {}
        self._maxlen = maxlen

    def append(self, channel: str, timestamp_epoch: float, value: float) -> None:
        """Append a single sample to the channel's buffer."""
        if channel not in self._buffers:
            self._buffers[channel] = deque(maxlen=self._maxlen)
        self._buffers[channel].append((timestamp_epoch, value))
        self._last_value[channel] = (timestamp_epoch, value)

    def get_history(self, channel: str) -> list[tuple[float, float]]:
        """Return a list copy of the channel's buffer for plotting."""
        buf = self._buffers.get(channel)
        if buf is None:
            return []
        return list(buf)

    def get_history_since(self, channel: str, since_epoch: float) -> list[tuple[float, float]]:
        """Return entries newer than since_epoch."""
        buf = self._buffers.get(channel)
        if buf is None:
            return []
        return [(t, v) for (t, v) in buf if t >= since_epoch]

    def get_last(self, channel: str) -> tuple[float, float] | None:
        """Return (timestamp, value) of the most recent sample, or None."""
        return self._last_value.get(channel)

    def known_channels(self) -> Iterable[str]:
        """Return iterable of all channels that have at least one sample."""
        return self._buffers.keys()

    def clear(self, channel: str | None = None) -> None:
        """Clear one channel or all channels."""
        if channel is None:
            self._buffers.clear()
            self._last_value.clear()
        else:
            self._buffers.pop(channel, None)
            self._last_value.pop(channel, None)
