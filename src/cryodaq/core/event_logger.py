"""Automatic event logging for system actions."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class EventLogger:
    """Logs system events to the operator journal via SQLiteWriter."""

    def __init__(self, writer: Any, experiment_manager: Any) -> None:
        self._writer = writer
        self._em = experiment_manager

    async def log_event(
        self,
        event_type: str,
        message: str,
        *,
        extra_tags: list[str] | None = None,
    ) -> None:
        """Write an auto-log entry. Fails silently on error."""
        try:
            await self._writer.append_operator_log(
                message=message,
                author="system",
                source="auto",
                experiment_id=self._em.active_experiment_id,
                tags=["auto", event_type, *(extra_tags or [])],
            )
        except Exception:
            logger.warning("Failed to auto-log event: %s", message, exc_info=True)
