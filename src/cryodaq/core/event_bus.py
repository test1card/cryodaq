"""Lightweight pub/sub event bus for engine events (not Reading data)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EngineEvent:
    """An engine-level event published to EventBus subscribers."""

    event_type: str  # "alarm_fired", "alarm_cleared", "phase_transition", "experiment_finalize", …
    timestamp: datetime
    payload: dict[str, Any]
    experiment_id: str | None = None


class EventBus:
    """Lightweight pub/sub for engine events (not Reading data).

    Subscribers receive a dedicated asyncio.Queue. Publish is non-blocking:
    a full queue logs a warning and drops the event rather than blocking
    the engine event loop.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, asyncio.Queue[EngineEvent]] = {}

    async def subscribe(self, name: str, *, maxsize: int = 1000) -> asyncio.Queue[EngineEvent]:
        """Register a named subscriber and return its dedicated queue."""
        if name in self._subscribers:
            logger.warning("EventBus: duplicate subscribe '%s' — replacing existing queue", name)
        q: asyncio.Queue[EngineEvent] = asyncio.Queue(maxsize=maxsize)
        self._subscribers[name] = q
        return q

    def unsubscribe(self, name: str) -> None:
        """Remove a subscriber by name. No-op if not registered."""
        self._subscribers.pop(name, None)

    async def publish(self, event: EngineEvent) -> None:
        """Fan out event to all subscriber queues (non-blocking; drops on full)."""
        for name, q in list(self._subscribers.items()):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "EventBus: subscriber '%s' queue full, dropping %s",
                    name,
                    event.event_type,
                )

    @property
    def subscriber_count(self) -> int:
        """Number of currently registered subscribers."""
        return len(self._subscribers)
