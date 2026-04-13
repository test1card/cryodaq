"""Continuous SRDG acquisition during calibration experiments."""

from __future__ import annotations

import logging
import math
from typing import Any

from cryodaq.drivers.base import ChannelStatus, Reading

logger = logging.getLogger(__name__)


class CalibrationAcquisitionService:
    """Records SRDG readings alongside normal KRDG during calibration runs.

    Activated when an experiment with ``calibration_acquisition: true``
    starts, deactivated when the experiment ends.  The scheduler calls
    :meth:`on_readings` after each LakeShore poll cycle.
    """

    def __init__(self, writer: Any) -> None:
        self._writer = writer
        self._active = False
        self._reference_channel: str | None = None
        self._target_channels: list[str] = []
        self._point_count = 0
        self._t_min: float | None = None
        self._t_max: float | None = None

    def activate(self, reference_channel: str, target_channels: list[str]) -> None:
        """Start recording SRDG for *target_channels*."""
        self._active = True
        self._reference_channel = reference_channel
        self._target_channels = list(target_channels)
        self._point_count = 0
        self._t_min = None
        self._t_max = None
        logger.info(
            "Calibration acquisition activated: ref=%s targets=%s",
            reference_channel,
            target_channels,
        )

    def deactivate(self) -> None:
        """Stop recording SRDG."""
        if self._active:
            logger.info(
                "Calibration acquisition deactivated (%d points, T %.1f–%.1f K)",
                self._point_count,
                self._t_min or 0,
                self._t_max or 0,
            )
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "active": self._active,
            "point_count": self._point_count,
            "t_min": self._t_min,
            "t_max": self._t_max,
            "reference_channel": self._reference_channel,
            "target_channels": self._target_channels,
        }

    def prepare_srdg_readings(
        self,
        krdg: list[Reading],
        srdg: list[Reading],
    ) -> list[Reading]:
        """Prepare SRDG readings for persistence (H.10: atomic with KRDG).

        Updates temperature range from reference KRDG channel and returns
        the list of SRDG readings to persist. The caller (Scheduler)
        persists them in the same transaction as KRDG readings.
        """
        if not self._active:
            return []

        # Update t_min / t_max from reference KRDG
        for r in krdg:
            if r.channel == self._reference_channel and r.status == ChannelStatus.OK:
                t = r.value
                if not math.isfinite(t) or t < 1.0:
                    continue
                if self._t_min is None or t < self._t_min:
                    self._t_min = t
                if self._t_max is None or t > self._t_max:
                    self._t_max = t

        # Build SRDG readings for target channels
        to_write: list[Reading] = []
        for reading in srdg:
            if reading.channel not in self._target_channels:
                continue
            if reading.status != ChannelStatus.OK:
                continue
            if not math.isfinite(reading.value):
                continue
            to_write.append(
                Reading(
                    timestamp=reading.timestamp,
                    instrument_id=reading.instrument_id,
                    channel=f"{reading.channel}_raw",
                    value=reading.value,
                    unit="sensor_unit",
                    status=ChannelStatus.OK,
                    raw=reading.value,
                    metadata={
                        "reading_kind": "calibration_srdg",
                        "source_channel": reading.channel,
                    },
                )
            )

        return to_write

    def on_srdg_persisted(self, count: int) -> None:
        """Update point counter after SRDG readings are persisted by scheduler."""
        self._point_count += count

    async def on_readings(
        self,
        krdg: list[Reading],
        srdg: list[Reading],
    ) -> None:
        """Legacy method — kept for backward compatibility.

        In the new H.10 flow, scheduler calls prepare_srdg_readings +
        on_srdg_persisted instead. This method still works but writes
        SRDG in a separate transaction (not atomic with KRDG).
        """
        if not self._active:
            return

        to_write = self.prepare_srdg_readings(krdg, srdg)
        if to_write:
            await self._writer.write_immediate(to_write)
            self._point_count += len(to_write)
