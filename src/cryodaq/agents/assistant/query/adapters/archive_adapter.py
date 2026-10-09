"""ArchiveAdapter — read-only access to the experiment archive for the query agent.

F33: thin wrapper over :class:`cryodaq.core.experiment.ExperimentManager` and
:class:`cryodaq.core.alarm_v2.AlarmStateManager`. The adapter never writes,
never invokes ZMQ commands, and never raises — it returns ``None`` on any
failure path so the format LLM can render a graceful "no data" reply.

The default time-window is 7 days for both archive listings and alarm-history
summaries, matching the architect's resolution in the F33 spec.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from cryodaq.agents.assistant.query.schemas import (
    AlarmHistoryResult,
    ArchiveDetailResult,
    ArchiveListResult,
)

if TYPE_CHECKING:
    from cryodaq.core.alarm_v2 import AlarmStateManager
    from cryodaq.core.experiment import ExperimentManager

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW_DAYS = 7
_DEFAULT_LIST_LIMIT = 20
_ALARM_HISTORY_FETCH_LIMIT = 1000


class ArchiveAdapter:
    """Read-only adapter exposing the experiment archive + alarm history."""

    def __init__(
        self,
        experiment_manager: ExperimentManager | None,
        alarm_v2_state_mgr: AlarmStateManager | None = None,
    ) -> None:
        self._em = experiment_manager
        self._alarm_v2 = alarm_v2_state_mgr

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
        if self._em is None:
            return None
        try:
            start_date = datetime.now(UTC) - timedelta(days=int(days))
            # ExperimentManager.list_archive_entries() scans the filesystem
            # and reads every metadata.json synchronously. Offload to a
            # thread so the Telegram / GUI query event loop stays responsive
            # for large archives. Cycle-2 fix for Codex finding on dc5350b.
            entries = await asyncio.to_thread(
                self._em.list_archive_entries,
                start_date=start_date,
                sort_by="start_time",
                descending=True,
            )
            entries = entries[: int(limit)]
            return ArchiveListResult(
                entries=[e.to_payload() for e in entries],
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
        if self._em is None:
            return None
        ident = (experiment_id or "").strip()
        if not ident:
            return None
        try:
            # Cycle-2 fix: get_archive_item rescans the archive directory and
            # reads every metadata.json under it. Offload to a thread to keep
            # the query event loop responsive.
            entry = await asyncio.to_thread(self._em.get_archive_item, ident)
            if entry is None:
                return None

            metadata: dict[str, Any] = {}
            try:
                # Cycle-2 fix: metadata.json read is synchronous file I/O —
                # offload so a slow disk or large file does not block the loop.
                metadata = json.loads(
                    await asyncio.to_thread(
                        entry.metadata_path.read_text, encoding="utf-8"
                    )
                )
            except Exception as meta_exc:  # noqa: BLE001
                logger.debug(
                    "ArchiveAdapter.get_detail: metadata.json read failed for %s: %s",
                    ident,
                    meta_exc,
                )
            phases_raw = metadata.get("phases", []) if isinstance(metadata, dict) else []
            phases: list[dict] = [
                dict(p) for p in phases_raw if isinstance(p, dict)
            ]

            duration_h: float | None = None
            if entry.start_time and entry.end_time:
                duration_h = (
                    entry.end_time - entry.start_time
                ).total_seconds() / 3600.0

            cooldown_phase = next(
                (
                    p
                    for p in phases
                    if str(p.get("phase", "")).lower() == "cooldown"
                    and p.get("ended_at")
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
                experiment_id=entry.experiment_id,
                sample=entry.sample,
                operator=entry.operator,
                status=entry.status,
                started_at=entry.start_time.isoformat()
                if entry.start_time is not None
                else "",
                ended_at=entry.end_time.isoformat()
                if entry.end_time is not None
                else None,
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
        if self._alarm_v2 is None:
            return None
        try:
            history = self._alarm_v2.get_history(limit=_ALARM_HISTORY_FETCH_LIMIT)
            cutoff = (datetime.now(UTC) - timedelta(days=int(days))).timestamp()

            triggered = 0
            cleared = 0
            by_alarm_id: dict[str, int] = {}

            for entry in history:
                if not isinstance(entry, dict):
                    continue
                try:
                    at = float(entry.get("at", 0.0))
                except (TypeError, ValueError):
                    continue
                if at < cutoff:
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
