"""ArchiveAdapter — read-only access to the experiment archive for the query agent.

F33: thin wrapper, never writes, never raises — returns ``None`` on any
failure path so the format LLM can render a graceful "no data" reply.

B1: previously called :class:`cryodaq.core.experiment.ExperimentManager`
and :class:`cryodaq.core.alarm_v2.AlarmStateManager` directly (in-process);
now calls the engine's existing read-only ``experiment_archive_list`` /
``experiment_get_archive_item`` / ``alarm_v2_history`` REP commands.
``metadata.json`` for archived (immutable, already-finalized) experiments
is still read directly from disk — it's a static file, not live engine
state, so no ZMQ round-trip is needed for it.

The default time-window is 7 days for both archive listings and alarm-
history summaries, matching the architect's resolution in the F33 spec.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryodaq.agents.assistant.query.schemas import (
    AlarmHistoryResult,
    ArchiveDetailResult,
    ArchiveListResult,
)
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW_DAYS = 7
_DEFAULT_LIST_LIMIT = 20
_ALARM_HISTORY_FETCH_LIMIT = 1000


class ArchiveAdapter:
    """Read-only adapter exposing the experiment archive + alarm history."""

    def __init__(self, engine_client: EngineQueryClient) -> None:
        self._client = engine_client

    # ------------------------------------------------------------------
    # Archive list
    # ------------------------------------------------------------------

    async def list_recent(
        self,
        *,
        days: int = _DEFAULT_WINDOW_DAYS,
        limit: int = _DEFAULT_LIST_LIMIT,
    ) -> ArchiveListResult | None:
        """Return up to ``limit`` archived experiments started within the last
        ``days`` days, newest first."""
        start_date = datetime.now(UTC) - timedelta(days=int(days))
        reply = await self._client.call(
            {
                "cmd": "experiment_archive_list",
                "start_date": start_date.isoformat(),
                "sort_by": "start_time",
                "descending": True,
            }
        )
        if not reply.get("ok"):
            return None
        try:
            entries = reply.get("entries", [])[: int(limit)]
            return ArchiveListResult(
                entries=entries,
                total_count=len(entries),
                filter_summary=f"за последние {int(days)} дней",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ArchiveAdapter.list_recent failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Archive detail
    # ------------------------------------------------------------------

    async def get_detail(self, experiment_id: str) -> ArchiveDetailResult | None:
        """Return the full record for one archived experiment, or ``None``."""
        ident = (experiment_id or "").strip()
        if not ident:
            return None
        reply = await self._client.call(
            {"cmd": "experiment_get_archive_item", "experiment_id": ident}
        )
        if not reply.get("ok"):
            return None
        entry = reply.get("entry")
        if entry is None:
            return None
        try:
            metadata: dict[str, Any] = {}
            meta_path_str = entry.get("metadata_path")
            if meta_path_str:
                try:
                    text = await asyncio.to_thread(
                        Path(meta_path_str).read_text, encoding="utf-8"
                    )
                    metadata = json.loads(text)
                except Exception as meta_exc:  # noqa: BLE001
                    logger.debug(
                        "ArchiveAdapter.get_detail: metadata.json read failed for %s: %s",
                        ident,
                        meta_exc,
                    )
            phases_raw = metadata.get("phases", []) if isinstance(metadata, dict) else []
            phases: list[dict] = [dict(p) for p in phases_raw if isinstance(p, dict)]

            start_time = entry.get("start_time")
            end_time = entry.get("end_time")
            duration_h: float | None = None
            if start_time and end_time:
                try:
                    duration_h = (
                        datetime.fromisoformat(end_time) - datetime.fromisoformat(start_time)
                    ).total_seconds() / 3600.0
                except ValueError:
                    duration_h = None

            cooldown_phase = next(
                (
                    p
                    for p in phases
                    if str(p.get("phase", "")).lower() == "cooldown" and p.get("ended_at")
                ),
                None,
            )
            cooldown_metrics: dict | None = None
            if cooldown_phase is not None:
                cooldown_metrics = {
                    "started_at": cooldown_phase.get("started_at"),
                    "ended_at": cooldown_phase.get("ended_at"),
                }

            return ArchiveDetailResult(
                experiment_id=entry.get("experiment_id", ident),
                sample=entry.get("sample", ""),
                operator=entry.get("operator", ""),
                status=entry.get("status", ""),
                started_at=start_time or "",
                ended_at=end_time,
                duration_h=duration_h,
                phases=phases,
                cooldown_metrics=cooldown_metrics,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ArchiveAdapter.get_detail failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Alarm history
    # ------------------------------------------------------------------

    async def alarm_history_summary(
        self,
        *,
        days: int = _DEFAULT_WINDOW_DAYS,
    ) -> AlarmHistoryResult | None:
        """Aggregate triggered/cleared transitions from the alarm-v2 history."""
        cutoff = (datetime.now(UTC) - timedelta(days=int(days))).timestamp()
        reply = await self._client.call(
            {
                "cmd": "alarm_v2_history",
                "start_ts": cutoff,
                "limit": _ALARM_HISTORY_FETCH_LIMIT,
            }
        )
        if not reply.get("ok"):
            return None
        try:
            history = reply.get("history", [])
            triggered = 0
            cleared = 0
            by_alarm_id: dict[str, int] = {}

            for entry in history:
                if not isinstance(entry, dict):
                    continue
                transition = str(entry.get("transition", "")).upper()
                alarm_id = str(entry.get("alarm_id", "unknown"))
                if transition == "TRIGGERED":
                    triggered += 1
                    by_alarm_id[alarm_id] = by_alarm_id.get(alarm_id, 0) + 1
                elif transition == "CLEARED":
                    cleared += 1

            return AlarmHistoryResult(
                window_description=f"за последние {int(days)} дней",
                triggered_count=triggered,
                cleared_count=cleared,
                by_alarm_id=by_alarm_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ArchiveAdapter.alarm_history_summary failed: %s", exc)
            return None
