"""Router for F30 Live Query Agent — dispatches QueryIntent to ServiceAdapters."""

from __future__ import annotations

import logging
from typing import Any

from cryodaq.agents.assistant.query.schemas import (
    QueryAdapters,
    QueryCategory,
    QueryIntent,
)

logger = logging.getLogger(__name__)


class QueryRouter:
    """Dispatches a classified QueryIntent to the appropriate ServiceAdapter.

    Returns a data dict with the fetched result, or None if dispatch failed.
    The data dict is category-specific and is passed to the format LLM in Phase C.
    """

    def __init__(self, adapters: QueryAdapters) -> None:
        self._adapters = adapters

    async def fetch(
        self,
        intent: QueryIntent,
        query: str,
    ) -> dict[str, Any]:
        """Fetch data for a classified intent. Never raises.

        Returns a dict with category-specific fields. Out-of-scope and unknown
        categories return an empty dict (no data fetch needed — format LLM handles it).
        """
        cat = intent.category
        try:
            if cat == QueryCategory.CURRENT_VALUE:
                return await self._fetch_current_value(intent)
            if cat == QueryCategory.ETA_COOLDOWN:
                return await self._fetch_eta_cooldown()
            if cat == QueryCategory.ETA_VACUUM:
                return await self._fetch_eta_vacuum()
            if cat == QueryCategory.RANGE_STATS:
                return await self._fetch_range_stats(intent)
            if cat == QueryCategory.PHASE_INFO:
                return await self._fetch_phase_info()
            if cat == QueryCategory.ALARM_STATUS:
                return await self._fetch_alarm_status()
            if cat == QueryCategory.COMPOSITE_STATUS:
                return await self._fetch_composite()
            # Out-of-scope and unknown: no data needed
            return {}
        except Exception as exc:
            logger.warning("QueryRouter.fetch failed for %s: %s", cat.value, exc)
            return {}

    async def _fetch_current_value(self, intent: QueryIntent) -> dict[str, Any]:
        channels = intent.target_channels or []
        snapshot = self._adapters.broker_snapshot
        readings = {}
        for ch in channels:
            r = await snapshot.latest(ch)
            if r is not None:
                readings[ch] = r
        # Also include age
        ages = {}
        for ch in channels:
            age = await snapshot.latest_age_s(ch)
            if age is not None:
                ages[ch] = age
        return {"readings": readings, "ages_s": ages, "channels": channels}

    async def _fetch_eta_cooldown(self) -> dict[str, Any]:
        eta = await self._adapters.cooldown.eta()
        return {"cooldown_eta": eta}

    async def _fetch_eta_vacuum(self) -> dict[str, Any]:
        eta = await self._adapters.vacuum.eta_to_target(1e-6)
        # Also get current pressure from snapshot
        snapshot = self._adapters.broker_snapshot
        all_ch = await snapshot.latest_all()
        current_p = None
        for ch, reading in all_ch.items():
            if "pressure" in ch.lower() or "mbar" in ch.lower():
                current_p = reading.value
                if eta is not None:
                    eta.current_mbar = current_p
                break
        return {"vacuum_eta": eta, "current_pressure": current_p}

    async def _fetch_range_stats(self, intent: QueryIntent) -> dict[str, Any]:
        channels = intent.target_channels or []
        window = intent.time_window_minutes or 60
        results = {}
        for ch in channels:
            stats = await self._adapters.sqlite.range_stats(ch, window)
            if stats is not None:
                results[ch] = stats
        # If no specific channels, try snapshot for pressure as default range
        if not channels:
            all_ch = await self._adapters.broker_snapshot.latest_all()
            for ch in all_ch:
                if "pressure" in ch.lower() or "mbar" in ch.lower():
                    stats = await self._adapters.sqlite.range_stats(ch, window)
                    if stats is not None:
                        results[ch] = stats
                    break
        return {"range_stats": results, "window_minutes": window}

    async def _fetch_phase_info(self) -> dict[str, Any]:
        status = await self._adapters.experiment.status()
        return {"experiment_status": status}

    async def _fetch_alarm_status(self) -> dict[str, Any]:
        result = await self._adapters.alarms.active()
        return {"alarm_result": result}

    async def _fetch_composite(self) -> dict[str, Any]:
        composite = await self._adapters.composite.status()
        return {"composite_status": composite}
