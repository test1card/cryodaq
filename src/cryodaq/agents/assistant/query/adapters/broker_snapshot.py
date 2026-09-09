"""BrokerSnapshot — latest-per-channel cache subscribing to the engine's ZMQ readings feed.

B1: previously subscribed to the in-process ``DataBroker`` directly; now
subscribes to the same ``tcp://127.0.0.1:5555`` PUB feed the GUI already
uses (:class:`cryodaq.core.zmq_bridge.ZMQSubscriber`) — the assistant
process is, for this purpose, just another read-only subscriber like the
GUI. Cache semantics (latest reading per channel, channel-name resolution)
are unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cryodaq.core.zmq_bridge import DEFAULT_PUB_ADDR, ZMQSubscriber

if TYPE_CHECKING:
    from cryodaq.core.channel_manager import ChannelManager
    from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)


def _elapsed_clock() -> float:
    """Seconds on a clock that never goes backwards AND counts suspended time.

    `time.monotonic()` excludes the time a laptop or a workstation spends
    suspended, so an hour of sleep leaves a reading from before it looking a
    second old. CLOCK_BOOTTIME includes it. The fallback matters only on
    platforms without it, where the understatement returns.
    """
    boottime = getattr(time, "CLOCK_BOOTTIME", None)
    if boottime is not None:
        try:
            return time.clock_gettime(boottime)
        except OSError:  # pragma: no cover - platform-dependent
            pass
    return time.monotonic()


class BrokerSnapshot:
    """Subscribes to the engine's readings feed and maintains a latest-per-channel cache.

    Read-only consumer. Safe to read from any coroutine; internal lock
    prevents torn reads.
    """

    def __init__(
        self,
        pub_addr: str = DEFAULT_PUB_ADDR,
        *,
        channel_manager: ChannelManager | None = None,
    ) -> None:
        self._channel_manager = channel_manager
        self._latest: dict[str, Reading] = {}
        #: When the most recent reading ARRIVED, on the monotonic clock.
        #:
        #: Not derivable from what is already stored. `Reading.timestamp` is the
        #: producer's wall clock, so a reading stamped an hour ahead makes the
        #: cache look fresh for an hour, and every timestamp-derived age moves
        #: when the system clock is corrected. Arrival is the only thing this
        #: process observes directly, and it is what "are readings arriving"
        #: actually means. Caught in review 2026-09-10, after two earlier
        #: attempts had answered that question from stored values instead.
        self._newest_arrival: float | None = None
        self._lock = asyncio.Lock()
        self._sub = ZMQSubscriber(pub_addr, callback=self._on_reading)

    async def _on_reading(self, reading: Reading) -> None:
        async with self._lock:
            self._latest[reading.channel] = reading
            self._newest_arrival = _elapsed_clock()

    async def start(self) -> None:
        await self._sub.start()
        logger.info("BrokerSnapshot started (ZMQ)")

    async def stop(self) -> None:
        await self._sub.stop()
        logger.info("BrokerSnapshot stopped")

    async def latest(self, channel: str) -> Reading | None:
        """Return latest reading, accepting canonical id OR display name.

        2026-05-08 (v0.56.3): drivers store ``Reading.channel`` as the
        full label from ``instruments.yaml`` (e.g. ``"Т1 Криостат верх"``),
        while ``QueryRouter._resolve_target_channels`` returns canonical
        short ids (``"Т1"``). Without this multi-tier lookup the snapshot
        hit-rate from the assistant pipeline is zero — every
        ``current_value`` query falls through to «нет данных».
        """
        async with self._lock:
            # Tier 1 — direct hit (display-name path).
            if channel in self._latest:
                return self._latest[channel]
            # Tier 2 — canonical id → display name via ChannelManager.
            if self._channel_manager is not None:
                try:
                    display = self._channel_manager.get_display_name(channel)
                except Exception:
                    display = None
                if display and display in self._latest:
                    return self._latest[display]
            # Tier 3 — prefix-match for "<canonical> <suffix>" labels
            # so the lookup also works without a ChannelManager bound.
            for key, reading in self._latest.items():
                if key == channel or key.startswith(channel + " "):
                    return reading
            return None

    async def knows(self, channel: str) -> bool:
        """Whether this channel is arriving, by id or by display name.

        The router validates a classifier's channel against channels.yaml,
        which describes the operator's thermometer set and contains neither the
        pressure gauge nor the source meter. Reviewed 2026-09-07: after the
        classifier was taught to name live channels, the router still threw the
        name away one layer later, so "какое давление" resolved to nothing —
        the fix was half done and the symptom unchanged.

        Deliberately reuses `latest`, so what the router accepts and what the
        fetch later finds cannot disagree.
        """
        return await self.latest(channel) is not None

    async def latest_all(self) -> dict[str, Reading]:
        async with self._lock:
            return dict(self._latest)

    async def latest_age_s(self, channel: str) -> float | None:
        reading = await self.latest(channel)
        if reading is None:
            return None
        return (datetime.now(UTC) - reading.timestamp).total_seconds()

    async def oldest_age_s(self) -> float | None:
        """Return age in seconds of the oldest cached reading, or None if empty."""
        async with self._lock:
            if not self._latest:
                return None
            now = datetime.now(UTC)
            return max((now - r.timestamp).total_seconds() for r in self._latest.values())

    async def arrival_age_s(self) -> float | None:
        """Seconds since the most recent reading ARRIVED, or None if none has.

        `oldest_age_s` answers "is some channel stale" from producer timestamps.
        This answers a different question -- is anything arriving at all -- and
        it must not be answered from producer timestamps at all:

        * the cache retains its last values indefinitely, so a full cache is
          compatible with an engine that stopped an hour ago;
        * a reading stamped in the FUTURE makes a timestamp-derived age negative
          now and comfortably small later, so a stopped stream reads as live as
          soon as wall time catches up;
        * correcting the system clock moves every timestamp-derived age.

        The monotonic clock is immune to all three, and arrival is the one thing
        this process observes with its own eyes.
        """
        async with self._lock:
            if self._newest_arrival is None:
                return None
            elapsed = _elapsed_clock() - self._newest_arrival
            if elapsed < 0.0:
                # The clock does not run backwards, so this is a paired-clock
                # violation rather than a fresh reading. Clamping it to 0 would
                # turn a broken invariant into the strongest possible evidence
                # of freshness, which is the wrong direction to fail.
                logger.warning("BrokerSnapshot: arrival clock went backwards by %.1fs", -elapsed)
                return None
            return elapsed

    def display_name(self, channel: str) -> str:
        """Return display name for channel from ChannelManager, or channel itself."""
        if self._channel_manager is not None:
            return self._channel_manager.get_display_name(channel)
        return channel

    def is_visible(self, channel: str) -> bool:
        """Whether the operator has this channel switched on. Unknown → visible.

        The default is True on purpose: derived and analytics channels are not
        in channels.yaml at all, and they must keep flowing. Only a channel the
        operator has explicitly unchecked answers False.
        """
        if self._channel_manager is not None:
            return self._channel_manager.is_visible(channel)
        return True

    async def latest_with_labels(self) -> dict[str, dict]:
        """Return all cached readings keyed by channel, enriched with display_name and unit."""
        async with self._lock:
            result: dict[str, dict] = {}
            for ch, reading in self._latest.items():
                result[ch] = {
                    "value": reading.value,
                    "unit": reading.unit,
                    "display_name": self.display_name(ch),
                    "visible": self.is_visible(ch),
                    "timestamp": reading.timestamp,
                    # CARRIED, because the value alone cannot be judged
                    # downstream. `Reading.is_usable()` is the repository's one
                    # predicate for a reading that means something — status OK
                    # and a finite value — and dropping it here is why a
                    # SENSOR_ERROR reading with a plausible number reached the
                    # operator as an ordinary measurement.
                    "usable": reading.is_usable(),
                }
            return result
