"""Per-channel reading history storage for the new dashboard.

Owned by DashboardView. Plot widgets, sensor cards, and phase-aware
widgets all read from this single source instead of duplicating
buffers across components.

Buffer maxlen matches the legacy OverviewPanel sample-count bound. At 1 Hz it
holds 24 hours; at higher acquisition rates the retained duration is shorter.
The GUI does not downsample ingestion, and 'Всё' means the whole retained
buffer rather than a guaranteed wall-clock duration.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable

# Bounded samples per channel; 86,400 equals 24 hours only at 1 Hz.
_BUFFER_MAXLEN = 86400


def peak_preserving_decimate(points: list[tuple[float, float]], target: int) -> list[tuple[float, float]]:
    """Bound points while retaining each bucket's extrema in time order."""
    if len(points) <= target:
        return points
    if target < 4:
        return [points[0], points[-1]][:target]

    interior = points[1:-1]
    bucket_count = max(1, (target - 2) // 2)
    bucket_size = max(1, math.ceil(len(interior) / bucket_count))
    result = [points[0]]
    for start in range(0, len(interior), bucket_size):
        bucket = interior[start : start + bucket_size]
        min_idx = min(range(len(bucket)), key=lambda idx: bucket[idx][1])
        max_idx = max(range(len(bucket)), key=lambda idx: bucket[idx][1])
        for idx in sorted({min_idx, max_idx}):
            result.append(bucket[idx])
    result.append(points[-1])
    return result


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
