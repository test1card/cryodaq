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

from cryodaq.drivers.base import ChannelStatus

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
        self._buffers: dict[str, deque[tuple[float, float, ChannelStatus]]] = {}
        self._last_value: dict[str, tuple[float, float, ChannelStatus]] = {}
        self._maxlen = maxlen

    def append(
        self,
        channel: str,
        timestamp_epoch: float,
        value: float,
        status: ChannelStatus = ChannelStatus.OK,
    ) -> None:
        """Append one full-rate sample without discarding its status evidence."""
        if channel not in self._buffers:
            self._buffers[channel] = deque(maxlen=self._maxlen)
        self._buffers[channel].append((timestamp_epoch, value, status))
        self._last_value[channel] = (timestamp_epoch, value, status)

    def prefill(
        self,
        channel: str,
        samples: Iterable[tuple[float, float]],
        status: ChannelStatus = ChannelStatus.OK,
    ) -> int:
        """Seed history OLDER than whatever this channel already holds.

        These buffers are filled only by live readings, so every relaunch began
        the plots again from empty: an experiment restarted three hours in
        showed three hours of nothing, while the PNG reports -- which read the
        database -- showed the whole run. The operator sees one instrument and
        two different histories, and the shorter one is the one they are
        watching while they work.

        Seeded samples go at the OLD end and never displace live ones. Anything
        at or after the oldest sample already held is dropped rather than
        merged: the live buffer is the authority for the period it covers, and
        interleaving two sources over the same interval is how a plot acquires
        points that no single record supports. Returns how many were accepted.
        """
        ordered = sorted((float(t), float(v)) for t, v in samples)
        if not ordered:
            return 0
        existing = self._buffers.get(channel)
        if existing:
            oldest_live = existing[0][0]
            ordered = [(t, v) for t, v in ordered if t < oldest_live]
            if not ordered:
                return 0
        # Bound the seed so it cannot evict the live tail it is extending.
        room = self._maxlen - (len(existing) if existing else 0)
        if room <= 0:
            return 0
        if len(ordered) > room:
            ordered = ordered[-room:]
        seeded = deque(
            ((timestamp, value, status) for timestamp, value in ordered),
            maxlen=self._maxlen,
        )
        seeded.extend(existing or ())
        self._buffers[channel] = seeded
        if channel not in self._last_value:
            timestamp, value = ordered[-1]
            self._last_value[channel] = (timestamp, value, status)
        return len(ordered)

    def oldest_timestamp(self, channel: str) -> float | None:
        """When this channel's retained history starts, or None if it holds nothing."""
        buf = self._buffers.get(channel)
        return buf[0][0] if buf else None

    def get_history(self, channel: str) -> list[tuple[float, float]]:
        """Return usable finite samples for plotting, excluding status failures."""
        buf = self._buffers.get(channel)
        if buf is None:
            return []
        return [
            (timestamp, value)
            for timestamp, value, status in buf
            if status is ChannelStatus.OK and math.isfinite(value)
        ]

    def get_history_since(self, channel: str, since_epoch: float) -> list[tuple[float, float]]:
        """Return entries newer than since_epoch."""
        buf = self._buffers.get(channel)
        if buf is None:
            return []
        return [
            (timestamp, value)
            for timestamp, value, status in buf
            if timestamp >= since_epoch and status is ChannelStatus.OK and math.isfinite(value)
        ]

    def get_last(self, channel: str) -> tuple[float, float] | None:
        """Return (timestamp, value) of the most recent sample, or None."""
        last = self._last_value.get(channel)
        return None if last is None else last[:2]

    def get_last_with_status(self, channel: str) -> tuple[float, float, ChannelStatus] | None:
        """Return the atomic latest timestamp, value, and status sample."""
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
