"""Router for F30 Live Query Agent — dispatches QueryIntent to ServiceAdapters."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import TYPE_CHECKING, Any

from cryodaq.agents.assistant.query.schemas import (
    QueryAdapters,
    QueryCategory,
    QueryIntent,
)

if TYPE_CHECKING:
    from cryodaq.core.channel_manager import ChannelManager

logger = logging.getLogger(__name__)


def _as_finite(value: Any) -> float | None:
    """A number that can be reported, or None. Booleans and NaN are not numbers here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


class QueryUnavailableError(RuntimeError):
    """Raised when the router cannot establish an authoritative query result."""


#: Units a reading must already be in to become `VacuumETA.current_mbar`.
#:
#: A STOPGAP SPECIFIC TO THIS STAND, not a rule about what a channel is for.
#: The one vacuum gauge here reports in mbar and the one known atmospheric
#: channel, `MultiLine_1/env_pressure`, reports in hPa, so the unit happens to
#: separate them. It does not separate them in general: a barometer configured
#: in mbar would pass this filter and be reported as the chamber pressure.
#:
#: And the hPa case is not a units error — 1 hPa IS 1 mbar. The number is
#: converted correctly and still wrong, because room air is not the chamber.
#: Pa would be a genuine factor of 100; that is a different mistake and this
#: filter excludes it too.
#:
#: The authority for "which channel is the vacuum gauge" is the descriptor, and
#: it takes all three of `quantity: pressure`, `role: primary_measurement` and
#: `safety_class: safety_critical_input` to name it. The last two alone are not
#: enough — Т11 and Т12 carry them as well, so a replacement that followed a
#: shorter rule could make a temperature the chamber pressure. Nothing on this
#: path can read descriptors yet; until it can, this narrows one confirmed live
#: path and claims nothing more.
_VACUUM_UNITS = frozenset({"mbar", "мбар"})


def _reading_is_usable(reading: object) -> bool:
    """`Reading.is_usable()`, and False when the object cannot answer.

    Fails closed: a stand-in without the predicate must not pass for a good
    reading merely because it could not be asked.
    """
    predicate = getattr(reading, "is_usable", None)
    if not callable(predicate):
        return False
    try:
        return predicate() is True
    except Exception:  # noqa: BLE001 - an unanswerable reading is not a usable one
        return False


class QueryRouter:
    """Dispatches a classified QueryIntent to the appropriate ServiceAdapter.

    Returns a category-specific data dict when dispatch succeeds, including
    authoritative empty results. Raises QueryUnavailableError when dispatch fails.
    The data dict is category-specific and is passed to the format LLM in Phase C.
    """

    def __init__(
        self,
        adapters: QueryAdapters,
        *,
        channel_manager: ChannelManager | None = None,
    ) -> None:
        self._adapters = adapters
        self._channel_manager = channel_manager

    async def _resolve_target_channels(self, intent: QueryIntent) -> list[str] | None:
        """Validate and resolve target_channels against current ChannelManager.

        Late binding: reads ChannelManager fresh on every call, picks up renames.
        """
        if not intent.target_channels:
            return None
        if self._channel_manager is None:
            return list(intent.target_channels)
        all_ids = set(self._channel_manager.get_all())
        resolved: list[str] = []
        for raw in intent.target_channels:
            raw_s = raw.strip()
            if raw_s in all_ids:
                resolved.append(raw_s)
                continue
            # Latin→Cyrillic normalization: "T12" → "Т12" (keyboard layout mismatch)
            norm_id = self._channel_manager.normalize_channel_id(raw_s)
            if norm_id != raw_s and norm_id in all_ids:
                resolved.append(norm_id)
                continue
            # F-ChannelLandmarks: consult landmark aliases (Т11/Т12) BEFORE
            # falling through to experiment-level name matching, so the
            # priority promised by the classifier prompt also holds at the
            # resolver layer when Gemma echoes an alias verbatim.
            landmark_id = self._channel_manager.find_by_landmark_alias(raw_s)
            if landmark_id:
                resolved.append(landmark_id)
                continue
            match_id = self._channel_manager.find_by_name(raw_s)
            if match_id:
                resolved.append(match_id)
                continue
            # Last: the channel may simply not be in channels.yaml. The gauge
            # and the source meter never have been, and the classifier is now
            # told they exist — so refusing them here would advertise a channel
            # and then drop it, which is what happened until 2026-09-07.
            snapshot = getattr(self._adapters, "broker_snapshot", None)
            if snapshot is not None and hasattr(snapshot, "knows"):
                try:
                    if await snapshot.knows(raw_s):
                        resolved.append(raw_s)
                        continue
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - resolution must not fail a query
                    logger.debug("QueryRouter: live-channel check unavailable: %s", exc)
            logger.warning("QueryRouter: cannot resolve target_channel %r to known ID", raw)
        return resolved if resolved else None

    async def fetch(
        self,
        intent: QueryIntent,
        query: str,
    ) -> dict[str, Any]:
        """Fetch authoritative data for a classified intent.

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
            if cat == QueryCategory.SYSTEM_HEALTH:
                return await self._fetch_system_health()
            # F33 — read-only archive queries.
            if cat == QueryCategory.ARCHIVE_LIST:
                return await self._fetch_archive_list(intent)
            if cat == QueryCategory.ARCHIVE_DETAIL:
                return await self._fetch_archive_detail(intent, query)
            if cat == QueryCategory.ALARM_HISTORY:
                return await self._fetch_alarm_history(intent)
            # F32 Stage 2 (v0.55.7) — semantic search over RAG corpus.
            if cat == QueryCategory.KNOWLEDGE_QUERY:
                return await self._fetch_knowledge_query(intent, query)
            # Out-of-scope and unknown: no data needed
            return {}
        except Exception as exc:
            logger.warning("QueryRouter.fetch failed for %s: %s", cat.value, exc)
            raise QueryUnavailableError(f"{cat.value} query unavailable") from exc

    async def _fetch_current_value(self, intent: QueryIntent) -> dict[str, Any]:
        channels = await self._resolve_target_channels(intent) or []
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
        # Target comes from the engine's configuration, which is where the
        # gauge's range is accounted for. A pressure hardcoded here can
        # ask for something this stand cannot measure.
        eta = await self._adapters.vacuum.eta_to_target()
        # Also get current pressure from snapshot
        snapshot = self._adapters.broker_snapshot
        all_ch = await snapshot.latest_all()
        # THE NAME OF A CHANNEL IS NOT EVIDENCE OF WHAT IT MEASURES. Matching
        # "pressure" in the channel id admits `MultiLine_1/env_pressure` — the
        # room's air, declared `role: environment`, `safety_class:
        # observational` — and whichever pressure-like channel the snapshot
        # yielded first won. With the barometer publishing before the gauge,
        # the operator asking how long the pump-down has left was told the
        # chamber sat at 1013, with no fault anywhere to explain it. Measured
        # on the committed code, not supposed.
        #
        # The unit filter below narrows that confirmed path on THIS stand,
        # where the gauge is in mbar and the barometer in hPa. It is not a rule
        # about purpose: a barometer configured in mbar would still pass. See
        # `_VACUUM_UNITS`.
        #
        # THE STATUS DECIDES WHETHER TO USE IT. `Reading.is_usable()` is the
        # repository's one predicate for a reading worth acting on, and every
        # acting path gates on it — the interlock, the alarms, the safety
        # manager. This path answers "сколько ещё откачивать" and used to take
        # the value whatever the gauge said about itself, so a SENSOR_ERROR
        # reading came back as "Давление сейчас: 1.23e-04".
        #
        # An unusable gauge is skipped rather than ending the search, so it no
        # longer hides a good one behind it. Which gauge wins among several
        # usable ones in millibars is whatever order the snapshot yields, as it
        # always was; choosing an authoritative channel is its own question.
        current_p = None
        for reading in all_ch.values():
            if (getattr(reading, "unit", "") or "").strip().lower() not in _VACUUM_UNITS:
                continue
            if not _reading_is_usable(reading):
                continue
            current_p = reading.value
            if eta is not None:
                eta.current_mbar = current_p
            break
        return {"vacuum_eta": eta, "current_pressure": current_p}

    async def _fetch_range_stats(self, intent: QueryIntent) -> dict[str, Any]:
        channels = await self._resolve_target_channels(intent) or []
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

    async def _fetch_system_health(self) -> dict[str, Any]:
        """Report what the assistant OBSERVES, and mark everything else unknown.

        The assistant is a separate process that sees the bus and nothing else.
        Readings arriving proves the engine is publishing; it proves nothing
        about the writer, the disk, or the locks, which live on the other side
        of a process boundary this code cannot cross.

        Every field is a three-state value -- True, False, or None for "not
        established" -- and never an optimistic default. Two review rounds each
        found an unknown wearing a reassurance: first a missing field read as
        "да", then `available is not False` turning an unknown availability into
        a confident one. Neither is a detail; both are the failure this category
        exists to prevent.
        """
        status = await self._adapters.composite.status()

        def _tristate(name: str) -> bool | None:
            value = getattr(status, name, None)
            return value if isinstance(value, bool) else None

        # The adapter marks a status unavailable when it could not read the
        # snapshot, and stale when the values are cached rather than current.
        # Unknown stays unknown: a status object that does not say is not a
        # status object that says yes.
        available = _tristate("available")
        stale = _tristate("stale")
        readable = available if available is not None else None
        current = None if readable is not True or stale is None else not stale

        key_channels = getattr(status, "key_temperatures", None)
        if not isinstance(key_channels, dict) or readable is not True:
            with_values = None
            total = None
        else:
            with_values = sum(1 for value in key_channels.values() if _as_finite(value) is not None)
            if _as_finite(getattr(status, "current_pressure", None)) is not None:
                with_values += 1
            total = len(key_channels) + 1

        return {
            "status_readable": readable,
            "values_are_current": current,
            "unreadable_reason": getattr(status, "reason", None) if readable is not True else None,
            # Whether the cache holds anything AT ALL -- not whether anything is
            # arriving. The cache keeps its last values indefinitely.
            "cache_empty": _tristate("snapshot_empty") if readable is True else None,
            # Seconds since anything ARRIVED: the only field that separates a
            # live engine from the last words a stopped one left behind.
            "arrival_age_s": getattr(status, "snapshot_arrival_age_s", None) if readable is True else None,
            # Age of the OLDEST: answers whether some channel has gone quiet.
            "oldest_age_s": getattr(status, "snapshot_age_s", None) if readable is True else None,
            # Cached entries, NOT an inventory of enabled channels: a channel
            # that has never published contributes to neither number.
            "key_channels_with_values": with_values,
            "key_channels_total": total,
            "alarms_available": _tristate("alarms_available") if readable is True else None,
        }

    async def _fetch_alarm_status(self) -> dict[str, Any]:
        result = await self._adapters.alarms.active()
        return {"alarm_result": result}

    async def _fetch_composite(self) -> dict[str, Any]:
        composite = await self._adapters.composite.status()
        return {"composite_status": composite}

    # ------------------------------------------------------------------
    # F33 — archive queries
    # ------------------------------------------------------------------

    @staticmethod
    def _days_from_intent(intent: QueryIntent, default_days: int = 7) -> int:
        """Convert ``time_window_minutes`` (the IntentClassifier's only time
        knob) to whole days, defaulting to ``default_days`` when absent.
        Minimum window is 1 day so the LLM cannot ask for "0 days"."""
        win = intent.time_window_minutes
        if win is None or win <= 0:
            return default_days
        return max(1, int(win) // 1440 or 1)

    async def _fetch_archive_list(self, intent: QueryIntent) -> dict[str, Any]:
        archive = self._adapters.archive
        if archive is None:
            return {"archive_list": None}
        days = self._days_from_intent(intent)
        result = await archive.list_recent(days=days)
        return {"archive_list": result}

    async def _fetch_archive_detail(self, intent: QueryIntent, query: str) -> dict[str, Any]:
        archive = self._adapters.archive
        if archive is None:
            return {"archive_detail": None}
        # Heuristic: the IntentClassifier may surface an experiment id via
        # ``quantity`` or as the only entry in ``target_channels`` (the LLM
        # sometimes treats it as a "channel"). Pass an empty candidate to the
        # adapter so it returns a typed invalid request, not an absence.
        candidate = (intent.quantity or "").strip()
        if not candidate and intent.target_channels:
            candidate = intent.target_channels[0].strip()
        result = await archive.get_detail(candidate)
        return {"archive_detail": result, "experiment_id": candidate}

    async def _fetch_alarm_history(self, intent: QueryIntent) -> dict[str, Any]:
        archive = self._adapters.archive
        if archive is None:
            return {"alarm_history": None}
        days = self._days_from_intent(intent)
        result = await archive.alarm_history_summary(days=days)
        return {"alarm_history": result}

    # ------------------------------------------------------------------
    # F32 Stage 2 (v0.55.7) — knowledge query
    # ------------------------------------------------------------------

    async def _fetch_knowledge_query(self, intent: QueryIntent, query: str) -> dict[str, Any]:
        """Run semantic search over the RAG corpus.

        ``query`` is preferred over ``intent.quantity`` because the original
        operator phrasing carries far more retrieval signal than the
        classifier's brief paraphrase. ``target_source_kind`` (when present)
        narrows the LanceDB ``WHERE`` clause to a single corpus kind.
        """
        adapter = self._adapters.rag
        if adapter is None or not getattr(adapter, "is_available", False):
            return {"knowledge_query": None, "query": query}
        result = await adapter.search(
            query,
            source_kind=intent.target_source_kind,
        )
        return {"knowledge_query": result, "query": query}
