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
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cryodaq.core.zmq_bridge import DEFAULT_PUB_ADDR, ZMQSubscriber

if TYPE_CHECKING:
    from cryodaq.core.channel_manager import ChannelManager
    from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)


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
        self._lock = asyncio.Lock()
        self._sub = ZMQSubscriber(pub_addr, callback=self._on_reading)

    async def _on_reading(self, reading: Reading) -> None:
        async with self._lock:
            self._latest[reading.channel] = reading

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
            return max(
                (now - r.timestamp).total_seconds() for r in self._latest.values()
            )

    def display_name(self, channel: str) -> str:
        """Return display name for channel from ChannelManager, or channel itself."""
        if self._channel_manager is not None:
            return self._channel_manager.get_display_name(channel)
        return channel

    async def latest_with_labels(self) -> dict[str, dict]:
        """Return all cached readings keyed by channel, enriched with display_name and unit."""
        async with self._lock:
            result: dict[str, dict] = {}
            for ch, reading in self._latest.items():
                result[ch] = {
                    "value": reading.value,
                    "unit": reading.unit,
                    "display_name": self.display_name(ch),
                    "timestamp": reading.timestamp,
                }
            return result
