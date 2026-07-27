"""Automatic event logging for system actions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cryodaq.core.event_bus import EventBus

logger = logging.getLogger(__name__)


class EventLogger:
    """Logs system events to the operator journal via SQLiteWriter."""

    def __init__(
        self,
        writer: Any,
        experiment_manager: Any,
        *,
        event_bus: EventBus | None = None,
    ) -> None:
        self._writer = writer
        self._em = experiment_manager
        self._event_bus = event_bus

    async def log_event(
        self,
        event_type: str,
        message: str,
        *,
        extra_tags: list[str] | None = None,
    ) -> None:
        """Write an auto-log entry to SQLite and publish to EventBus."""
        experiment_id = self._em.active_experiment_id
        try:
            await self._writer.append_operator_log(
                message=message,
                author="system",
                source="auto",
                experiment_id=experiment_id,
                tags=["auto", event_type, *(extra_tags or [])],
            )
        except Exception:
            logger.warning("Failed to auto-log event: %s", message, exc_info=True)

        if self._event_bus is not None:
            from cryodaq.core.event_bus import EngineEvent

            try:
                await self._event_bus.publish(
                    EngineEvent(
                        event_type="event_logged",
                        timestamp=datetime.now(UTC),
                        payload={"event_type": event_type, "message": message},
                        experiment_id=experiment_id,
                    )
                )
            except Exception:
                logger.warning("EventBus publish failed in log_event", exc_info=True)
