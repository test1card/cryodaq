"""ChartDispatcher — fire-and-forget chart attachment for query responses."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from cryodaq.agents.assistant.query.schemas import QueryCategory
from cryodaq.notifications.charts import render_temperature_chart

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

SendPhoto = Callable[[int | str, bytes], Awaitable[None]]


def _log_task_exception(task: asyncio.Task) -> None:
    """Done-callback that surfaces chart task exceptions to the logger."""
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Chart dispatch task failed")


class ChartDispatcher:
    """Dispatches PNG temperature charts for qualifying query categories.

    Fires as a background asyncio task; never blocks the query response path.
    All exceptions are caught and logged via _log_task_exception done-callback.
    """

    def __init__(self, send_photo: SendPhoto) -> None:
        self._send_photo = send_photo

    def dispatch(
        self,
        category: QueryCategory,
        data: dict[str, Any],
        chat_id: int | str,
    ) -> None:
        """Schedule chart dispatch as a background task (fire-and-forget).

        Only dispatches for composite_status and range_stats. No-ops for other
        categories or when snapshot is empty.
        """
        if category not in (QueryCategory.COMPOSITE_STATUS, QueryCategory.RANGE_STATS):
            return
        task = asyncio.create_task(
            self._maybe_send(category, data, chat_id),
            name="chart_dispatch",
        )
        task.add_done_callback(_log_task_exception)

    async def _maybe_send(
        self,
        category: QueryCategory,
        data: dict[str, Any],
        chat_id: int | str,
    ) -> None:
        if category == QueryCategory.COMPOSITE_STATUS:
            await self._send_composite_chart(data, chat_id)
        elif category == QueryCategory.RANGE_STATS:
            await self._send_range_chart(data, chat_id)

    async def _send_composite_chart(
        self, data: dict[str, Any], chat_id: int | str
    ) -> None:
        cs = data.get("composite_status")
        if cs is None:
            return
        if getattr(cs, "snapshot_empty", False):
            return
        temps = getattr(cs, "key_temperatures", {})
        if not temps:
            return
        chart = render_temperature_chart(temps)
        if chart:
            await self._send_photo(chat_id, chart)

    async def _send_range_chart(
        self, data: dict[str, Any], chat_id: int | str
    ) -> None:
        stats = data.get("range_stats", {})
        if not stats:
            return
        # Build a simple bar chart from range min/max/mean for each channel
        means: dict[str, float | None] = {}
        for ch, s in stats.items():
            if hasattr(s, "mean_value"):
                means[ch] = s.mean_value
        if not means:
            return
        chart = render_temperature_chart(means, title="Среднее за период")
        if chart:
            await self._send_photo(chat_id, chart)
