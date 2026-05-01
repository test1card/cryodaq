"""CompositeAdapter — parallel fetch of all engine state for composite_status."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from cryodaq.agents.assistant.query.schemas import CompositeStatus

logger = logging.getLogger(__name__)


class CompositeAdapter:
    """Parallel-fetches all adapters for composite_status queries.

    One failed adapter never blocks the others (return_exceptions=True).
    """

    def __init__(
        self,
        *,
        broker_snapshot,
        cooldown,
        vacuum,
        alarms,
        experiment,
    ) -> None:
        self._snapshot = broker_snapshot
        self._cooldown = cooldown
        self._vacuum = vacuum
        self._alarms = alarms
        self._experiment = experiment

    async def status(self) -> CompositeStatus:
        labeled_data, cd_eta, vac_eta, alarm_result, exp_status = await asyncio.gather(
            self._snapshot.latest_with_labels(),
            self._cooldown.eta(),
            self._vacuum.eta_to_target(1e-6),
            self._alarms.active(),
            self._experiment.status(),
            return_exceptions=True,
        )

        if isinstance(labeled_data, Exception):
            logger.warning("CompositeAdapter: snapshot failed: %s", labeled_data)
            labeled_data = {}
        if isinstance(cd_eta, Exception):
            logger.warning("CompositeAdapter: cooldown failed: %s", cd_eta)
            cd_eta = None
        if isinstance(vac_eta, Exception):
            logger.warning("CompositeAdapter: vacuum failed: %s", vac_eta)
            vac_eta = None
        if isinstance(alarm_result, Exception):
            logger.warning("CompositeAdapter: alarms failed: %s", alarm_result)
            alarm_result = None
        if isinstance(exp_status, Exception):
            logger.warning("CompositeAdapter: experiment failed: %s", exp_status)
            exp_status = None

        snapshot_empty = len(labeled_data) == 0

        # Build key_temperatures from ALL temperature channels (unit == "K")
        key_temps: dict[str, float | None] = {}
        current_pressure: float | None = None
        for ch, info in labeled_data.items():
            unit = info.get("unit", "")
            val = info.get("value")
            display = info.get("display_name", ch)
            if unit == "K":
                key_temps[display] = val
            elif unit in ("mbar", "Pa") and current_pressure is None:
                current_pressure = val

        active_alarms = getattr(alarm_result, "active", []) if alarm_result else []

        if vac_eta is not None and vac_eta.current_mbar is None and current_pressure is not None:
            vac_eta.current_mbar = current_pressure

        # Snapshot age for defensive empty-snapshot messaging
        snapshot_age_s: float | None = None
        if hasattr(self._snapshot, "oldest_age_s"):
            try:
                snapshot_age_s = await self._snapshot.oldest_age_s()
            except Exception:
                pass

        return CompositeStatus(
            timestamp=datetime.now(UTC),
            experiment=exp_status,
            cooldown_eta=cd_eta,
            vacuum_eta=vac_eta,
            active_alarms=active_alarms,
            key_temperatures=key_temps,
            current_pressure=current_pressure,
            snapshot_empty=snapshot_empty,
            snapshot_age_s=snapshot_age_s,
        )
