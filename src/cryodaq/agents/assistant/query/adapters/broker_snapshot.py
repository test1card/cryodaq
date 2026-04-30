"""BrokerSnapshot — latest-per-channel cache subscribing to DataBroker."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryodaq.core.broker import DataBroker
    from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

_SUBSCRIBER_NAME = "assistant_query_snapshot"


class BrokerSnapshot:
    """Subscribes to DataBroker and maintains a latest-per-channel cache.

    Read-only consumer. No state mutation on broker. Safe to read from any
    coroutine; internal lock prevents torn reads.
    """

    def __init__(self, broker: DataBroker) -> None:
        self._broker = broker
        self._latest: dict[str, Reading] = {}
        self._lock = asyncio.Lock()
        self._queue: asyncio.Queue[Reading] | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._queue = await self._broker.subscribe(
            _SUBSCRIBER_NAME, maxsize=1000
        )
        self._task = asyncio.create_task(
            self._consume_loop(), name="broker_snapshot_consume"
        )
        logger.info("BrokerSnapshot started")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._broker.unsubscribe(_SUBSCRIBER_NAME)
        logger.info("BrokerSnapshot stopped")

    async def _consume_loop(self) -> None:
        assert self._queue is not None
        while True:
            try:
                reading = await self._queue.get()
                async with self._lock:
                    self._latest[reading.channel] = reading
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("BrokerSnapshot consume error: %s", exc)

    async def latest(self, channel: str) -> Reading | None:
        async with self._lock:
            return self._latest.get(channel)

    async def latest_all(self) -> dict[str, Reading]:
        async with self._lock:
            return dict(self._latest)

    async def latest_age_s(self, channel: str) -> float | None:
        reading = await self.latest(channel)
        if reading is None:
            return None
        return (datetime.now(UTC) - reading.timestamp).total_seconds()
