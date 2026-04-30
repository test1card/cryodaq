"""CompositeAdapter — parallel fetch of all engine state for composite_status."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from cryodaq.agents.assistant.query.schemas import CompositeStatus

logger = logging.getLogger(__name__)

# Channels to include in key_temperatures (subset; config override in future)
_KEY_TEMP_CHANNELS = ("T_cold", "T_warm", "T_shield", "T_4K", "T_50K")


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
        snapshot_all, cd_eta, vac_eta, alarm_result, exp_status = await asyncio.gather(
            self._snapshot.latest_all(),
            self._cooldown.eta(),
            self._vacuum.eta_to_target(1e-6),
            self._alarms.active(),
            self._experiment.status(),
            return_exceptions=True,
        )

        # Gracefully handle any per-adapter Exception
        if isinstance(snapshot_all, Exception):
            logger.warning("CompositeAdapter: snapshot failed: %s", snapshot_all)
            snapshot_all = {}
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

        key_temps: dict[str, float | None] = {}
        for ch in _KEY_TEMP_CHANNELS:
            reading = snapshot_all.get(ch)
            key_temps[ch] = reading.value if reading is not None else None

        pressure_reading = None
        for ch, reading in snapshot_all.items():
            if "pressure" in ch.lower() or "mbar" in ch.lower():
                pressure_reading = reading
                break
        current_pressure = pressure_reading.value if pressure_reading else None

        active_alarms = getattr(alarm_result, "active", []) if alarm_result else []

        if vac_eta is not None and vac_eta.current_mbar is None:
            for ch, reading in snapshot_all.items():
                if "pressure" in ch.lower() or "mbar" in ch.lower():
                    vac_eta.current_mbar = reading.value
                    break

        return CompositeStatus(
            timestamp=datetime.now(UTC),
            experiment=exp_status,
            cooldown_eta=cd_eta,
            vacuum_eta=vac_eta,
            active_alarms=active_alarms,
            key_temperatures=key_temps,
            current_pressure=current_pressure,
        )
